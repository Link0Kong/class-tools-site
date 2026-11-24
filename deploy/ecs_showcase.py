# -*- coding: utf-8 -*-
"""产品展示页发布：`class-tools-showcase/dist` → https://tool.furina.fun/showcase/

为什么要单独一个脚本（2026-11-24 上线）：
  - 展示页是独立静态站（300+ 文件 / ≈29 MB，含五端实拍 webp 与下载包），
    不属于 `web/tools` 那个单文件应用，`ecs_site.py apply` 的固定文件清单拉不到它；
  - 展示页必须与主站**同域**：同一笔网站备案（闽ICP备2026042939号-2 +
    闽公网安备35010202002375号）。另开域名/子站属于另一笔网站备案
    （见 docs/公安联网备案/05_备案后与配套事项.md §2），所以挂在主站的 /showcase/ 子路径；
  - Caddy 是 `root * /var/www/tool` + `file_server`，目录放进去即可访问，**不需要改 Caddyfile**。

流程（OSS 仍是静态内容唯一真源，和 sync_tools.py / ecs_site.py 同一口径）：
  pack   → 本机把 dist 打成 tar.gz（部署名 showcase/site.tar.gz）
  upload → 上传 OSS 公共读桶 tool-furina-fun（香港）
  apply  → pack + upload + 云助手在 ECS 解包到 /var/www/tool/showcase（原子换目录 + 备案号自检）
  verify → 本机校验线上字节、两个备案号、图标与静态资源

用法（在 `web` 目录下，用系统 python）：
  python deploy\\ecs_showcase.py apply            # 打包 + 上传 + 部署（最常用）
  python deploy\\ecs_showcase.py verify           # 只校验线上
  python deploy\\ecs_showcase.py pack             # 只打包
  python deploy\\ecs_showcase.py apply --dry-run  # 只打印远端脚本
  python deploy\\ecs_showcase.py apply --src "D:\\path\\to\\dist"   # 指定别的构建目录

凭据：复用 `deploy/sync_tools.py::load_creds()`（环境变量或 deploy/creds.env 的
ALIYUN_AK_ID / ALIYUN_AK_SECRET），脚本**不打印任何凭据**。
"""
import argparse
import hashlib
import os
import sys
import tarfile
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import ecs_site  # noqa: E402  （复用云助手通道 / 常量 / 校验工具）

SHOWCASE_SRC = os.path.normpath(os.path.join(HERE, "..", "..", "class-tools-showcase", "dist"))
TAR_PATH = os.path.join(HERE, "_build", "showcase-site.tar.gz")
OSS_KEY = "showcase/site.tar.gz"
URL_PATH = "/showcase/"
ICP = "闽ICP备2026042939号-2"
GONGAN = "闽公网安备35010202002375号"
GONGAN_CODE = "35010202002375"
MIN_TAR = 5 * 1024 * 1024      # 实际 ≈29 MB；小于 5 MB 说明打包目录不对
MIN_INDEX = 4000               # index.html 实际约 12 KB


# ---------------------------------------------------------------- 本机打包 / 上传


def pack(src=None, quiet=False):
    src = os.path.abspath(src or SHOWCASE_SRC)
    index = os.path.join(src, "index.html")
    if not os.path.isfile(index):
        raise SystemExit("展示页源码目录不对（找不到 index.html）：%s" % src)
    html = open(index, encoding="utf-8").read()
    for token in (ICP, GONGAN, "media/gongan.png",
                  "https://beian.miit.gov.cn/",
                  "https://beian.mps.gov.cn/#/query/webSearch?code=" + GONGAN_CODE):
        if token not in html:
            raise SystemExit("index.html 缺少备案信息标记：%s（先补页脚再发布）" % token)
    if not os.path.isfile(os.path.join(src, "media", "gongan.png")):
        raise SystemExit("缺少公安备案图标：media/gongan.png")

    os.makedirs(os.path.dirname(TAR_PATH), exist_ok=True)
    entries = []
    for root, dirs, names in os.walk(src):
        dirs.sort()
        for n in sorted(names):
            p = os.path.join(root, n)
            entries.append((p, os.path.relpath(p, src).replace("\\", "/")))
    mtime = int(os.path.getmtime(index))
    with tarfile.open(TAR_PATH, "w:gz", compresslevel=6) as tf:
        for p, arc in entries:
            info = tf.gettarinfo(p, arcname=arc)
            info.uid = info.gid = 0
            info.uname = info.gname = ""
            info.mtime = mtime
            with open(p, "rb") as fh:
                tf.addfile(info, fh)
    size = os.path.getsize(TAR_PATH)
    if size < MIN_TAR:
        raise SystemExit("tar.gz 只有 %d B，明显不完整（至少 %d B）" % (size, MIN_TAR))
    if not quiet:
        print("[pack] %d 个文件 → %s（%.2f MB）" % (len(entries), TAR_PATH, size / 1048576.0))
    return TAR_PATH


def upload(quiet=False):
    import oss2
    import sync_tools

    ak, sk = sync_tools.load_creds()
    bucket = oss2.Bucket(oss2.Auth(ak, sk), "https://%s.aliyuncs.com" % sync_tools.REGION,
                         sync_tools.BUCKET)
    bucket.put_object_from_file(OSS_KEY, TAR_PATH, headers={
        "Content-Type": "application/gzip", "Cache-Control": "no-cache"})
    head = bucket.head_object(OSS_KEY)
    local = os.path.getsize(TAR_PATH)
    if head.content_length != local:
        raise SystemExit("OSS 字节不一致：本地 %d / 远端 %d" % (local, head.content_length))
    if not quiet:
        print("[upload] OSS %s %d B（一致）" % (OSS_KEY, local))


# ---------------------------------------------------------------- 远端脚本


def build_apply_script():
    return r"""#!/bin/bash
set -e
TS=$(date +%Y%m%d-%H%M%S)
BASE="__OSS_BASE__"
KEY="__OSS_KEY__"
TAR="/tmp/showcase-site.tar.gz"
TMP="/var/www/tool/showcase.new.$TS"
BK="/var/www/tool_backup/$TS"
mkdir -p "$TMP" "$BK" /var/www/tool

echo "=== 1. 从 OSS 下载打包 ==="
curl -fsSL --retry 3 --retry-delay 2 --max-time 900 -o "$TAR" "$BASE/$KEY"
SZ=$(stat -c%s "$TAR")
echo "tar.gz=$SZ B"
if [ "$SZ" -lt __MIN_TAR__ ]; then echo "FATAL tar.gz 太小: $SZ"; exit 3; fi

echo "=== 2. 解包并自检 ==="
tar -xzf "$TAR" -C "$TMP"
IN_SZ=$(stat -c%s "$TMP/index.html")
echo "index.html=$IN_SZ B"
if [ "$IN_SZ" -lt __MIN_INDEX__ ]; then echo "FATAL index.html 太小: $IN_SZ"; exit 4; fi
grep -q "__ICP__" "$TMP/index.html" || { echo "FATAL index.html 缺 ICP 备案号"; exit 5; }
grep -q "__GONGAN__" "$TMP/index.html" || { echo "FATAL index.html 缺公安联网备案号"; exit 6; }
grep -q "https://beian.miit.gov.cn/" "$TMP/index.html" || { echo "FATAL ICP 号没有链接工信部系统"; exit 7; }
grep -q "code=__GONGAN_CODE__" "$TMP/index.html" || { echo "FATAL 公安备案号查询链接缺失"; exit 8; }
[ -f "$TMP/media/gongan.png" ] || { echo "FATAL 缺 media/gongan.png"; exit 9; }
[ -f "$TMP/style.css" ] && [ -f "$TMP/app.js" ] || { echo "FATAL 静态资源不全"; exit 10; }
grep -q "foot-legal" "$TMP/style.css" || { echo "FATAL style.css 缺备案页脚样式"; exit 11; }

echo "=== 3. 原子替换 /var/www/tool/showcase ==="
if [ -d /var/www/tool/showcase ]; then mv /var/www/tool/showcase "$BK/showcase.old"; fi
mv "$TMP" /var/www/tool/showcase
chmod -R a+rX /var/www/tool/showcase
rm -f "$TAR"
echo "files=$(find /var/www/tool/showcase -type f | wc -l) size=$(du -sh /var/www/tool/showcase | cut -f1)"
sha256sum /var/www/tool/showcase/index.html

echo "=== 4. 本机 HTTP 校验（:80 IP 入口，不经过 308） ==="
for p in /showcase/ /showcase/style.css /showcase/media/gongan.png /showcase/media/web/campus.webp; do
  code=$(curl -s -m 10 -o /dev/null -w '%{http_code}' "http://127.0.0.1$p" || echo ERR)
  size=$(curl -s -m 10 -o /dev/null -w '%{size_download}' "http://127.0.0.1$p" || echo 0)
  echo "$p -> $code ($size B)"
done
echo "=== done: $(date -Is) ==="
""".replace("__OSS_BASE__", ecs_site.OSS_BASE) \
   .replace("__OSS_KEY__", OSS_KEY) \
   .replace("__MIN_TAR__", str(MIN_TAR)) \
   .replace("__MIN_INDEX__", str(MIN_INDEX)) \
   .replace("__ICP__", ICP) \
   .replace("__GONGAN__", GONGAN) \
   .replace("__GONGAN_CODE__", GONGAN_CODE)


def apply(dry_run=False):
    pack()
    if dry_run:
        print(build_apply_script())
        return 0
    upload()
    script = build_apply_script()
    st, rc, out = ecs_site.run_script(script, timeout=900, wait=1200, label="showcase")
    print(out)
    print("[结果] status=%s exit=%s" % (st, rc))
    if st != "Success" or rc not in (0, "0", None):
        return 1
    return verify()


# ---------------------------------------------------------------- 本机校验


def _fetch(url, headers=None, timeout=60):
    req = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.status, dict(r.headers), r.read()


def verify():
    print("=== 本机校验 %s%s ===" % (ecs_site.SITE, URL_PATH))
    local = open(os.path.join(SHOWCASE_SRC, "index.html"), "rb").read()
    st, hd, body = _fetch(ecs_site.SITE + URL_PATH, {"Accept-Encoding": "identity"})
    print("GET %s -> HTTP %s, %d B" % (URL_PATH, st, len(body)))
    print("本地 index.html %d B sha256=%s" % (len(local), hashlib.sha256(local).hexdigest()))
    print("线上 index.html %d B sha256=%s -> %s" % (
        len(body), hashlib.sha256(body).hexdigest(),
        "MATCH" if body == local else "MISMATCH"))
    text = body.decode("utf-8", "replace")
    ok = True
    for token, name in ((ICP, "ICP 备案号"), (GONGAN, "公安联网备案号"),
                        ("https://beian.miit.gov.cn/", "工信部备案系统链接"),
                        ("code=" + GONGAN_CODE, "公安备案查询链接"),
                        ("media/gongan.png", "公安备案图标引用"),
                        ("foot-legal", "备案页脚样式")):
        hit = token in text
        ok = ok and hit
        print("  %-14s %s" % (name, "OK" if hit else "缺失"))
    st, hd, _ = _fetch(ecs_site.SITE + URL_PATH + "media/gongan.png")
    print("图标 GET -> HTTP %s, %s, %s B" % (st, hd.get("Content-Type"), hd.get("Content-Length")))
    ok = ok and st == 200
    for path in ("style.css", "app.js", "media/web/campus.webp", "media/brand.svg"):
        try:
            st, hd, b = _fetch(ecs_site.SITE + URL_PATH + path)
            print("%-24s HTTP %s %8d B %s" % (path, st, len(b), hd.get("Content-Type", "")))
            ok = ok and st == 200
        except Exception as exc:  # noqa: BLE001
            print("%-24s ERR %s" % (path, exc.__class__.__name__))
            ok = False
    st, hd, gz = _fetch(ecs_site.SITE + URL_PATH, {"Accept-Encoding": "gzip"})
    print("gzip: HTTP %s Content-Encoding=%s 传输 %d B（未压缩 %d B）"
          % (st, hd.get("Content-Encoding"), len(gz), len(body)))
    if body != local:
        ok = False
    print("=== %s ===" % ("PASS" if ok else "FAIL"))
    return 0 if ok else 1


# ---------------------------------------------------------------- main


def main(argv=None):
    ap = argparse.ArgumentParser(description="产品展示页发布（/showcase/，云助手 + OSS）")
    ap.add_argument("cmd", choices=["pack", "apply", "verify"])
    ap.add_argument("--src", help="展示页构建目录（默认 G:\\ClassTools\\class-tools-showcase\\dist）")
    ap.add_argument("--dry-run", action="store_true", help="只打印远端脚本，不上传不执行")
    ns = ap.parse_args(argv)
    if ns.cmd == "pack":
        pack(ns.src)
        return 0
    if ns.cmd == "verify":
        return verify()
    return apply(ns.dry_run)


if __name__ == "__main__":
    sys.exit(main())
