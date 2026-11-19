# -*- coding: utf-8 -*-
"""Android 版本发布：自动上传 APK + latest.json 到更新渠道（ECS + OSS）。

2026-11-19 用户要求：安卓所有版本发布都要自动上传更新渠道。
本脚本是唯一发布入口，供 android-class-tools 的 `assembleRelease` finalizer 调用：
  1) 计算 APK SHA-256 / 大小，生成 latest.json（版本号、更新说明、sha256、sizeBytes）；
  2) 上传 OSS `android/<file>.bin`（APK 以 octet-stream 存；OSS 禁止公开 .apk 直链）；
  3) 通过 ECS 云助手从 OSS 拉取并落到 `/var/www/tool/android/<file>.apk`；
  4) 上传 `android/latest.json` 到 OSS 与 ECS（先 APK 后 JSON，避免客户端拿到 404 URL）；
  5) 验证 ECS JSON / APK / OSS JSON 均 200 且 sha 一致；写回 web/android/latest.json。

用法（在 web 目录下）：
  python deploy\\android_release.py --apk <path> --version-name 1.0.0-beta8 --version-code 91
  python deploy\\android_release.py ... --dry-run
  python deploy\\android_release.py ... --force        # 同版本同 sha 也重传
凭据：复用 deploy/sync_tools.py::load_creds()（creds.env / 环境变量），不打印凭据。
"""
import argparse
import base64
import hashlib
import json
import os
import sys
import time
import urllib.request
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
WEB = os.path.dirname(HERE)
sys.path.insert(0, HERE)

import sync_tools  # noqa: E402
import ecs_site  # noqa: E402

ANDROID_DIR = os.path.join(WEB, "android")
OSS_BASE = "https://tool-furina-fun.oss-cn-hongkong.aliyuncs.com"
ECS_ANDROID = "/var/www/tool/android"
ECS_IP = ecs_site.ECS_IP


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def safe_name(version_name):
    s = "".join(c if (c.isalnum() or c in "._-") else "-" for c in str(version_name))
    return s.strip("-") or "release"


def oss_bucket():
    import oss2
    ak, sk = sync_tools.load_creds()
    return oss2.Bucket(oss2.Auth(ak, sk), "https://oss-cn-hongkong.aliyuncs.com", "tool-furina-fun")


def http_code(url, method="GET", timeout=30):
    req = urllib.request.Request(url, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read() if method == "GET" else b""
    except Exception as e:  # noqa: BLE001
        return 0, str(e).encode("utf-8", "replace")


def main(argv=None):
    ap = argparse.ArgumentParser(description="发布 Android 版本到更新渠道（ECS + OSS）")
    ap.add_argument("--apk", required=True, help="release APK 路径")
    ap.add_argument("--version-name", required=True)
    ap.add_argument("--version-code", required=True, type=int)
    ap.add_argument("--notes", default="")
    ap.add_argument("--channel", default="beta")
    ap.add_argument("--force", action="store_true", help="同版本同 sha 也重传")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--skip-oss", action="store_true", help="只发 ECS（不推荐）")
    ap.add_argument("--skip-ecs", action="store_true", help="只发 OSS（不推荐）")
    args = ap.parse_args(argv)

    apk = os.path.abspath(args.apk)
    if not os.path.isfile(apk):
        raise SystemExit("APK 不存在：%s" % apk)
    digest = sha256(apk)
    size = os.path.getsize(apk)
    fname = "classtools-%s.apk" % safe_name(args.version_name)
    oss_name = fname + ".bin"
    notes = args.notes.strip() or ("%s（测试版本）" % args.version_name)
    payload = {
        "versionCode": int(args.version_code),
        "versionName": str(args.version_name),
        "apkUrl": "%s/android/%s" % (OSS_BASE, oss_name),
        "notes": notes,
        "force": False,
        "channel": str(args.channel or "beta"),
        "sha256": digest,
        "sizeBytes": size,
    }
    raw = (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8")

    print("== Android 更新渠道发布 ==")
    print("  APK      : %s" % apk)
    print("  version  : %s / vc%s" % (args.version_name, args.version_code))
    print("  size/sha : %d B / %s" % (size, digest))
    print("  APK URL  : %s" % payload["apkUrl"])
    if args.dry_run:
        print("  [dry-run] 不上传")
        return 0

    # 幂等：同一 versionCode + sha 已经是渠道当前版本时不再重传（--force 可覆盖）。
    old = None
    try:
        with open(os.path.join(ANDROID_DIR, "latest.json"), encoding="utf-8") as f:
            old = json.load(f)
    except Exception:  # noqa: BLE001
        old = None
    if not args.force and old and int(old.get("versionCode") or 0) == int(args.version_code):
        if str(old.get("sha256") or "") == digest:
            print("  渠道已是该版本与该 sha，跳过上传（--force 可重传）")
        else:
            # 同 versionCode 但构建产物不同：不允许静默覆盖渠道；发新版本必须 bump versionCode。
            print("  渠道已有同 versionCode（%s）但 sha 不同；请 bump versionCode 后再发布（--force 可强制覆盖）"
                  % args.version_code)
        return 0

    os.makedirs(ANDROID_DIR, exist_ok=True)
    local_apk = os.path.join(ANDROID_DIR, fname)
    local_bin = os.path.join(ANDROID_DIR, oss_name)
    # 本地留档（同字节；发布脚本自身不依赖这两份文件）
    import shutil
    shutil.copy2(apk, local_apk)
    shutil.copy2(apk, local_bin)
    # 1) OSS：先 APK，后 JSON
    if not args.skip_oss:
        b = oss_bucket()
        b.put_object_from_file("android/" + oss_name, apk, headers={
            "Content-Type": "application/octet-stream", "Cache-Control": "no-cache"})
        # 关键：必须上传本次生成的 raw，而不是本地 latest.json（本地只在全部校验通过后才更新，
        # 否则会把上一版 JSON 传到 OSS，出现 ECS/OSS 版本分裂）。
        b.put_object("android/latest.json", raw, headers={
            "Content-Type": "application/json; charset=utf-8", "Cache-Control": "no-cache"})
        print("  OSS 上传完成：android/%s + android/latest.json" % oss_name)

    # 2) ECS：从 OSS 拉 APK（云助手脚本只含固定 OSS URL / sha / origin），再写 latest.json
    if not args.skip_ecs:
        b64_json = base64.b64encode(raw).decode("ascii")
        script = "\n".join([
            "set -euo pipefail",
            "mkdir -p %s" % ECS_ANDROID,
            "TMP=$(mktemp /tmp/classtools-android.XXXXXX)",
            'cleanup(){ rm -f "$TMP"; }',
            "trap cleanup EXIT",
            'curl -fsSL --retry 3 --retry-delay 2 --max-time 300 -o "$TMP" "%s/android/%s"' % (OSS_BASE, oss_name),
            'echo "%s  $TMP" | sha256sum -c -' % digest,
            'install -m 0644 "$TMP" "%s/%s"' % (ECS_ANDROID, fname),
            'echo "%s" | base64 -d > "%s/latest.json"' % (b64_json, ECS_ANDROID),
            'chmod 0644 "%s/latest.json"' % ECS_ANDROID,
            'curl -fsS -m 8 -o /tmp/android-latest.check "http://127.0.0.1/android/latest.json"',
            'python3 -c "import json;d=json.load(open(\'/tmp/android-latest.check\'));assert d[\'versionCode\']==%d' % int(args.version_code) + '"',
            'curl -fsS -m 20 -o /dev/null "http://127.0.0.1/android/%s"' % fname,
            'rm -f /tmp/android-latest.check',
            'echo "ECS_ANDROID_OK %s %s"' % (fname, digest),
        ]) + "\n"
        status, code, out = ecs_site.run_script(script, timeout=360, wait=480, label="android-release")
        print(out.strip()[-1200:])
        if status != "Success" or str(code) not in ("0", "None"):
            raise SystemExit("ECS 更新渠道发布失败：status=%s exit=%s" % (status, code))

    # 3) 公网验证（ECS + OSS）
    checks = [
        ("ECS latest.json", "http://%s/android/latest.json" % ECS_IP, "GET"),
        ("ECS APK", "http://%s/android/%s" % (ECS_IP, fname), "HEAD"),
        ("OSS latest.json", OSS_BASE + "/android/latest.json", "GET"),
        ("OSS APK.bin", payload["apkUrl"], "HEAD"),
    ]
    for label, url, method in checks:
        code, body = http_code(url, method)
        print("  %-16s HTTP %s  %s" % (label, code, url))
        if code != 200:
            raise SystemExit("验证失败：%s HTTP %s" % (label, code))
        if method == "GET" and "latest.json" in url:
            remote = json.loads(body.decode("utf-8"))
            if str(remote.get("sha256")) != digest or int(remote.get("versionCode") or 0) != int(args.version_code):
                raise SystemExit("验证失败：%s 内容与发布不一致" % label)

    # 只有公网双通道都验证通过后才写本地 latest.json（失败时下次不会被幂等跳过）
    with open(os.path.join(ANDROID_DIR, "latest.json"), "w", encoding="utf-8") as f:
        f.write(raw.decode("utf-8"))

    print("== 发布完成：%s / vc%s / %s ==" % (args.version_name, args.version_code, digest))
    print("  客户端主入口：http://%s/android/latest.json" % ECS_IP)
    print("  OSS 兜底    ：%s/android/latest.json" % OSS_BASE)
    return 0


if __name__ == "__main__":
    sys.exit(main())
