# -*- coding: utf-8 -*-
"""本地临时通道自检：起一个 local_channel 子进程 → headless Edge 真实登录 → 验证数据与工具可用。

用法（在 web 目录）：
    python deploy/local_channel_selftest.py
依赖：本机 Edge + `tools/tests/_qa_v2/_cdp.py`（既有测试基座）。只用**测试身份**
（学号 3260799999 / 姓名 测试账号）登录，不涉及真实同学账号；自检结束自动停掉通道进程。
"""
import json
import os
import socket
import subprocess
import sys
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
WEB = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(WEB, "tools", "tests", "_qa_v2"))
import _cdp  # noqa: E402

TEST_SID = "3260799999"
TEST_NAME = "测试账号"
SHOTS = os.path.join(HERE, "_shots_local_channel")


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def wait_http(url, timeout=15):
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            with urllib.request.urlopen(url, timeout=2) as r:
                if r.status == 200:
                    return True
        except Exception:
            time.sleep(0.2)
    return False


def main():
    os.makedirs(SHOTS, exist_ok=True)
    port = free_port()
    base = "http://127.0.0.1:%d/" % port
    py = sys.executable
    proc = subprocess.Popen([py, os.path.join(HERE, "local_channel.py"), "--port", str(port)],
                            cwd=WEB, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                            encoding="utf-8", errors="replace")
    page = None
    browser = None
    ok = False
    try:
        assert wait_http(base + "__chan/health"), "local_channel 未在 15s 内启动"
        print("[selftest] channel up:", base)
        browser = _cdp.Browser(window=(1280, 800))
        page = browser.new_page(base)
        page.set_device(1280, 800, dpr=1.0, mobile=False, touch=False)
        page.wait_load(30)
        # 1) 身份门禁可见
        gate = page.wait_for("!!document.getElementById('igGo')", 10)
        print("[selftest] identity gate visible:", gate)
        page.screenshot(os.path.join(SHOTS, "01_gate.png"))
        # 2) 输入测试身份并登录
        page.evaluate("(function(){var s=document.getElementById('igSid');s.value=%s;"
                      "var n=document.getElementById('igName');n.value=%s;})()"
                      % (json.dumps(TEST_SID), json.dumps(TEST_NAME)))
        page.evaluate("document.getElementById('igGo').click()")
        ready = page.wait_for("(function(){try{return !document.body.classList.contains('id-locked')"
                              "&&!!document.querySelector('#tabsBar button');}catch(e){return false;}})()", 30)
        print("[selftest] login -> app ready:", ready)
        page.sleep(1.5)
        chip = page.evaluate("(document.getElementById('idChipTxt')||{}).textContent||''")
        print("[selftest] identity chip:", chip)
        page.screenshot(os.path.join(SHOTS, "02_logged_in.png"))
        # 3) 通过通道的 CloudBase 请求
        urls = page.network_urls()
        cb = [u for u in urls if "/__cb/" in u]
        print("[selftest] proxied cloud requests:", len(cb), "| sample:", cb[:3])
        # 4) 工具可用：全部页 → 演示（PPT 模块加载）
        page.evaluate("(function(){var b=document.querySelector('#tabsBar button[data-tab=all]');if(b)b.click();})()")
        card = page.wait_for("!!document.querySelector('#allCards [data-open=ppt]')", 10)
        if card:
            page.evaluate("(function(){var c=document.querySelector('#allCards [data-open=ppt]');if(c)c.click();})()")
        ppt_ok = page.wait_for("!!window.PPT", 10)
        page.sleep(1.2)
        page.screenshot(os.path.join(SHOTS, "03_ppt_tab.png"))
        print("[selftest] all-page card ppt:", card, "| window.PPT:", ppt_ok)
        # 5) 错误收集
        errs = page.all_errors()
        if isinstance(errs, dict):
            flat = [str(x) for v in errs.values() for x in (v if isinstance(v, list) else [v])]
        else:
            flat = [str(x) for x in (errs or [])]
        real = [e for e in flat if "favicon" not in e.lower()]
        print("[selftest] console/network errors:", len(real), real[:3])
        ok = bool(ready and chip.strip() == TEST_NAME and len(cb) > 0 and ppt_ok and len(real) == 0)
        if not ok and page is not None:
            page.screenshot(os.path.join(SHOTS, "99_fail.png"))
    finally:
        try:
            if page is not None:
                page.close()
        except Exception:
            pass
        try:
            if browser is not None:
                browser.close()
        except Exception:
            pass
        try:
            proc.terminate()
            proc.wait(timeout=8)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass
    print("RESULT:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
