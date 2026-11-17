# -*- coding: utf-8 -*-
"""用本机 Edge headless + CDP 做页面级检查（不依赖第三方包，websocket-client 即可）。

前置：已启动 Edge：
  msedge --headless=new --remote-debugging-port=9333 --user-data-dir=<temp> about:blank

运行：
  python preview_check.py
"""
from __future__ import annotations

import base64
import json
import sys
import time
from pathlib import Path

import requests
import websocket

ROOT = Path(__file__).resolve().parent.parent
OUT = Path(__import__("tempfile").gettempdir()) / "legal_preview"
PORT = 9333
WIDTHS = [360, 390, 430, 768, 960, 1280, 1440]


def get_page_ws() -> str:
    targets = requests.get("http://127.0.0.1:%d/json/list" % PORT, timeout=10).json()
    pages = [t for t in targets if t.get("type") == "page" and t.get("url") != "edge://sync-confirmation-dialog/"]
    if not pages:
        raise SystemExit("没有可用的 page target")
    return pages[0]["webSocketDebuggerUrl"]


class CDP:
    def __init__(self, url: str):
        self.ws = websocket.create_connection(url, timeout=20)
        self.n = 0

    def cmd(self, method: str, params: dict | None = None, timeout: float = 20):
        self.n += 1
        mid = self.n
        self.ws.send(json.dumps({"id": mid, "method": method, "params": params or {}}))
        end = time.time() + timeout
        while time.time() < end:
            raw = self.ws.recv()
            msg = json.loads(raw)
            if msg.get("id") == mid:
                if "error" in msg:
                    raise RuntimeError("%s: %s" % (method, msg["error"]))
                return msg.get("result", {})
        raise TimeoutError(method)

    def eval(self, expr: str):
        r = self.cmd(
            "Runtime.evaluate",
            {"expression": expr, "returnByValue": True, "awaitPromise": True},
        )
        if r.get("exceptionDetails"):
            raise RuntimeError(r["exceptionDetails"])
        return r.get("result", {}).get("value")


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    cdp = CDP(get_page_ws())
    cdp.cmd("Page.enable")
    cdp.cmd("Runtime.enable")
    cdp.cmd("Emulation.setEmulatedMedia", {"media": "screen"})
    cdp.cmd(
        "Page.addScriptToEvaluateOnNewDocument",
        {
            "source": """
window.__previewErrors=[];
addEventListener('error',function(e){window.__previewErrors.push(String(e.message||e));});
addEventListener('unhandledrejection',function(e){window.__previewErrors.push(String(e.reason||e));});
"""
        },
    )

    errors = []
    checks = 0
    pages = sorted(ROOT.glob("**/*.html"))
    if len(pages) != 11:
        errors.append("HTML 数量不是 11：%d" % len(pages))

    for path in pages:
        uri = path.as_uri()
        rel = path.relative_to(ROOT)
        for width in WIDTHS:
            height = 844 if width < 600 else 900
            mobile = width < 600
            cdp.cmd(
                "Emulation.setDeviceMetricsOverride",
                {
                    "width": width,
                    "height": height,
                    "deviceScaleFactor": 1,
                    "mobile": mobile,
                },
            )
            cdp.cmd("Page.navigate", {"url": uri})
            for _ in range(60):
                try:
                    if cdp.eval("document.readyState") == "complete":
                        break
                except Exception:  # noqa: BLE001
                    pass
                time.sleep(0.05)
            time.sleep(0.12)
            info = cdp.eval(
                """(() => {
  const de=document.documentElement, b=document.body;
  const tw=Array.from(document.querySelectorAll('.table-wrap'));
  const toc=document.querySelector('.toc details');
  const res=performance.getEntriesByType('resource').map(e=>e.name).filter(n=>/^https?:/i.test(n));
  return {
    title: document.title,
    h1: document.querySelectorAll('h1').length,
    h2: document.querySelectorAll('h2').length,
    tables: document.querySelectorAll('table').length,
    links: document.querySelectorAll('a[href]').length,
    overflow: Math.max(de.scrollWidth, b.scrollWidth) - window.innerWidth,
    tableWraps: tw.length,
    tocOpen: toc ? toc.hasAttribute('open') : null,
    external: res,
    errs: window.__previewErrors || [],
    textLen: (b.innerText || '').length,
  };
})()"""
            )
            checks += 1
            if info["overflow"] > 1:
                errors.append("%s @%d 横向溢出 %dpx" % (rel, width, info["overflow"]))
            if info["external"]:
                errors.append("%s @%d 外部请求：%s" % (rel, width, info["external"][:3]))
            if info["errs"]:
                errors.append("%s @%d JS 错误：%s" % (rel, width, info["errs"][:3]))
            if info["h1"] != 1:
                errors.append("%s @%d h1 数量 %d" % (rel, width, info["h1"]))
            if info["tocOpen"] is not None:
                if width > 960 and info["tocOpen"] is not True:
                    errors.append("%s @%d 桌面目录未展开" % (rel, width))
                if width <= 960 and info["tocOpen"] is not False:
                    errors.append("%s @%d 移动端目录未收起（%s）" % (rel, width, info["tocOpen"]))
            min_len = 3000 if rel.name == "index.html" else 5000
            if info["textLen"] < min_len:
                errors.append("%s @%d 正文过短 %d" % (rel, width, info["textLen"]))

        # 打印媒体：导航应被隐藏
        cdp.cmd("Emulation.setEmulatedMedia", {"media": "print"})
        print_hidden = cdp.eval(
            "getComputedStyle(document.querySelector('.site-head')).display === 'none' && "
            "(!document.querySelector('.toc') || getComputedStyle(document.querySelector('.toc')).display === 'none')"
        )
        if not print_hidden:
            errors.append("%s 打印样式未隐藏导航" % rel)
        cdp.cmd("Emulation.setEmulatedMedia", {"media": "screen"})

    # 截图：首页 1280 / 390，网页端隐私 1280 / 390，深色 1280
    for path, width, height, name in [
        (ROOT / "index.html", 1280, 900, "index_1280.png"),
        (ROOT / "index.html", 390, 844, "index_390.png"),
        (ROOT / "web" / "privacy.html", 1280, 900, "web_privacy_1280.png"),
        (ROOT / "web" / "privacy.html", 390, 844, "web_privacy_390.png"),
    ]:
        cdp.cmd(
            "Emulation.setDeviceMetricsOverride",
            {"width": width, "height": height, "deviceScaleFactor": 1, "mobile": width < 600},
        )
        cdp.cmd("Page.navigate", {"url": path.as_uri()})
        for _ in range(60):
            try:
                if cdp.eval("document.readyState") == "complete":
                    break
            except Exception:  # noqa: BLE001
                pass
            time.sleep(0.05)
        time.sleep(0.15)
        shot = cdp.cmd("Page.captureScreenshot", {"format": "png"})
        (OUT / name).write_bytes(base64.b64decode(shot["data"]))
        print("shot", OUT / name)

    # 深色
    cdp.cmd(
        "Emulation.setDeviceMetricsOverride",
        {"width": 1280, "height": 900, "deviceScaleFactor": 1, "mobile": False},
    )
    cdp.cmd(
        "Emulation.setEmulatedMedia",
        {"features": [{"name": "prefers-color-scheme", "value": "dark"}]},
    )
    cdp.cmd("Page.navigate", {"url": (ROOT / "web" / "privacy.html").as_uri()})
    time.sleep(0.3)
    dark_bg = cdp.eval("getComputedStyle(document.body).backgroundColor")
    if dark_bg != "rgb(17, 22, 20)":
        errors.append("深色模式 body 背景异常：%s" % dark_bg)
    shot = cdp.cmd("Page.captureScreenshot", {"format": "png"})
    (OUT / "web_privacy_dark_1280.png").write_bytes(base64.b64decode(shot["data"]))
    cdp.cmd("Emulation.setEmulatedMedia", {"features": []})

    print("checks=%d" % checks)
    if errors:
        print("FAIL %d" % len(errors))
        for e in errors:
            print(" -", e)
        return 1
    print("PASS：11 页 × %d 宽度无溢出/无外部请求/无 JS 错误；打印与深色检查通过" % len(WIDTHS))
    return 0


if __name__ == "__main__":
    sys.exit(main())
