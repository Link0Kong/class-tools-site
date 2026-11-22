# -*- coding: utf-8 -*-
"""网页端「联网基址」静态守卫（2026-11-22 事故回归）。

背景：2026-11-21 的公开仓库整理把 index.html 里的 ECS IP `121.196.47.2`
批量替换成了域名 `tool.furina.fun`；而 `tool.furina.fun` 备案期 DNS 为 NXDOMAIN、
CloudBase 网关 CORS 白名单又只放行该域名/127.0.0.1 —— 公网 IP 入口的页面
因此把 PostgREST 请求打到跨源网关（预检 403），表现为「登录网络错误 / 整站联网异常」。
本测试锁死「域名 + ECS IP 双入口」的基址语义，防止再次被批量替换/重构改坏。

只读静态检查，不联网、不起浏览器。运行：python tools\\tests\\v2_net_base_check.py
"""
import os
import re
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.abspath(os.path.join(HERE, "..", "index.html"))

R = []


def T(name, ok, note=""):
    R.append((bool(ok), name, str(note)))


def lines_with(text, needle):
    return [ln.strip() for ln in text.splitlines() if needle in ln]


def main():
    text = open(SRC, encoding="utf-8").read()

    # 1. 云端字面量必须保留（部署脚本靠它解析网关）
    T("var CB 网关字面量保留（https://…/v1/rdb/rest/）",
      bool(re.search(r'var CB="https://[^"]+/v1/rdb/rest/"', text)))
    T("var CBK 可发布密钥保留（anon JWT）",
      bool(re.search(r'var CBK="eyJ[A-Za-z0-9_\-\.]+"', text)))

    # 2. 同源反代：域名 **和 ECS IP** 都要命中（IP 入口是备案期唯一公网入口）
    cb = lines_with(text, "v1/rdb/rest/")
    cbline = next((ln for ln in cb if "location.origin" in ln and "test(h)" in ln), "")
    T("CB 同源覆盖：命中 tool.furina.fun 子域",
      "tool\\.furina\\.fun" in cbline, cbline[:120])
    T("CB 同源覆盖：命中 ECS IP 121.196.47.2",
      'h==="121.196.47.2"' in cbline, cbline[:120])
    T("CB 同源覆盖：改走同源 /v1/rdb/rest/",
      'location.origin+"/v1/rdb/rest/"' in cbline, cbline[:120])
    T("CB 同源覆盖：不存在冗余的 h===\"tool.furina.fun\" 判断",
      'h==="tool.furina.fun"' not in text)

    # 3. 抽签核验链接：IP 入口下用同源 origin（否则链接指向 NXDOMAIN 域名）
    dv = next((ln for ln in lines_with(text, "base=location.origin")), "")
    T("drawVerifyUrl：命中 ECS IP", 'h==="121.196.47.2"' in dv, dv[:120])

    # 4. PPT 下载/媒体缓存：http 页面固定 ECS 地址（https 页面同源 /pptfiles）
    T("PPT_ECS_BASE = http://121.196.47.2/pptfiles",
      'var PPT_ECS_BASE="http://121.196.47.2/pptfiles";' in text)
    T("PPT_ECS_BASE 未被改成死域名",
      'PPT_ECS_BASE="https://tool.furina.fun/pptfiles"' not in text)

    # 5. 大屏互联 / 文件传输 drop 基址：两个副本的 http 分支都用 ECS IP
    T("drop 基址：http 页面 → http://121.196.47.2/drop（两处代码+两处 catch 兜底）",
      text.count('"http://121.196.47.2/drop"') == 4,
      "count=%d" % text.count('"http://121.196.47.2/drop"'))
    T("drop 基址未被改成死域名",
      '"https://tool.furina.fun/drop"' not in text)

    # 6. 扫码登录账号服务：IP/域名/本机走同源 /account
    qa = next((ln for ln in lines_with(text, "account") if "location.origin" in ln and "47" in ln), "")
    T("扫码登录 apiBase：ECS IP 走同源 /account", "121\\.196\\.47\\.2" in qa, qa[:140])
    T("扫码登录 apiBase：保留裸 IP 兜底 http://121.196.47.2/account",
      '"http://121.196.47.2/account"' in text)

    # 7. 反向守卫：任何「写死访问域名」的网络基址都只允许出现在品牌/分享链接/OSS 直连页兜底
    #    （死域名 + 混合内容/跨源会再次造成联网异常；注释与 <span> 品牌文案不算）
    allowed = [
        "<title>", "brand:", "wm:", "var head=", "var base=", "/account",
        "app:", "a.download=", 'o.app!==', '"tool.furina.fun"',
    ]
    leftovers = []
    for ln in text.splitlines():
        if not re.search(r'https?://tool\.furina\.fun/', ln):
            continue
        s = ln.strip()
        if s.startswith(("/*", "*", "//", "<!--")) or "121.196.47.2" in s:
            continue
        if not any(a in s for a in allowed):
            leftovers.append(s[:120])
    T("无「域名顶替 IP」的残留网络基址", not leftovers, leftovers[:4])

    n_pass = sum(1 for ok, _, _ in R if ok)
    for ok, name, note in R:
        print(("[PASS] " if ok else "[FAIL] ") + name + (("  | " + note) if note else ""))
    print("=" * 72)
    print("v2_net_base_check: %d 项，PASS %d，FAIL %d" % (len(R), n_pass, len(R) - n_pass))
    print("=" * 72)
    return 0 if n_pass == len(R) else 1


if __name__ == "__main__":
    sys.exit(main())
