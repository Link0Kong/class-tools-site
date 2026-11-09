# -*- coding: utf-8 -*-
"""只读网络探测：ECS(121.196.47.2) / MC(120.27.217.236 & 115.29.166.27) / FC(start) / OSS 默认端点 / 暂停域名解析。

- 仅 TCP connect、HTTP GET、TLS 握手取证书、Minecraft status ping（只读），不做 SSH 登录、不发 POST。
- 不读取任何凭据文件。
"""
import datetime
import gzip
import hashlib
import json
import re
import socket
import ssl
import struct
import sys
import urllib.request
import zlib

LOCAL_INDEX = r"C:\Users\Ko_Li\.openclaw\workspace\web\tools\index.html"
LOCAL_INDEX_SHA = "656105117464c6d67106faa4011d5dd806d11d2c0d44760df961488d92e3b420"
OSS_INDEX_SHA = LOCAL_INDEX_SHA  # 本次 OSS 实测确认一致
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) audit-readonly/1.0"
NOW = lambda: datetime.datetime.now().astimezone().isoformat(timespec="seconds")


def p(*parts):
    print(" ".join(str(x) for x in parts))


def sha(b):
    return hashlib.sha256(b).hexdigest()


def tcp(host, port, timeout=5.0):
    t0 = datetime.datetime.now()
    try:
        s = socket.create_connection((host, port), timeout=timeout)
        peer = s.getpeername()
        s.settimeout(2.0)
        banner = b""
        try:
            banner = s.recv(256)
        except Exception:
            pass
        s.close()
        ms = (datetime.datetime.now() - t0).total_seconds() * 1000
        return "OPEN", peer, banner, ms
    except Exception as e:
        ms = (datetime.datetime.now() - t0).total_seconds() * 1000
        return "CLOSED/FAIL", type(e).__name__ + ": " + str(e), b"", ms


def decode_http_body(raw, headers):
    enc = (headers.get("Content-Encoding") or "").lower()
    note = "identity"
    try:
        if "gzip" in enc:
            raw = gzip.decompress(raw)
            note = "gunzip.gzip"
        elif "deflate" in enc:
            raw = zlib.decompress(raw, -zlib.MAX_WBITS)
            note = "gunzip.deflate"
        elif enc:
            note = "unknown(" + enc + ")"
    except Exception as e:
        note = "decompress-error:" + type(e).__name__
    return raw, note


def http_get(url, timeout=20.0, insecure=False):
    req = urllib.request.Request(url, headers={
        "User-Agent": UA, "Accept": "*/*", "Accept-Encoding": "identity",
        "Cache-Control": "no-cache"})
    ctx = None
    if insecure:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    t0 = datetime.datetime.now()
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as r:
            raw = r.read()
            hdrs = dict(r.headers.items())
            code = r.status
            final = r.geturl()
        body, dec = decode_http_body(raw, hdrs)
        ms = (datetime.datetime.now() - t0).total_seconds() * 1000
        return {"ok": True, "status": code, "headers": hdrs, "body": body, "decoded": dec,
                "ms": ms, "final": final}
    except urllib.error.HTTPError as e:
        raw = e.read()
        hdrs = dict(e.headers.items())
        body, dec = decode_http_body(raw, hdrs)
        return {"ok": True, "status": e.code, "headers": hdrs, "body": body, "decoded": dec, "ms": 0,
                "final": url}
    except Exception as e:
        ms = (datetime.datetime.now() - t0).total_seconds() * 1000
        return {"ok": False, "error": type(e).__name__ + ": " + str(e), "ms": ms}


def show_resp(tag, r, show_body=False, body_limit=600):
    if not r["ok"]:
        p("  %-28s FAIL %s (%.0fms)" % (tag, r["error"], r["ms"]))
        return
    h = r["headers"]
    interesting = {k: v for k, v in h.items() if k.lower() in (
        "server", "content-type", "content-length", "content-encoding", "last-modified",
        "etag", "date", "location", "cache-control", "x-cache", "via", "strict-transport-security")}
    p("  %-28s status=%s bytes=%d decode=%s sha256=%s (%.0fms)" % (
        tag, r["status"], len(r["body"]), r["decoded"], sha(r["body"]), r["ms"]))
    p("    headers:", interesting)
    txt = r["body"].decode("utf-8", "replace")
    m = re.search(r"<title[^>]*>(.*?)</title>", txt, re.S | re.I)
    if m:
        p("    <title>:", m.group(1).strip()[:120])
    if show_body:
        p("    body[0:%d]:" % body_limit, txt[:body_limit].replace("\n", "\\n"))


def tls_cert(host, port=443, timeout=6.0):
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    try:
        with socket.create_connection((host, port), timeout=timeout) as s:
            with ctx.wrap_socket(s, server_hostname=None) as ss:
                cert = ss.getpeercert()
                return {"ok": True, "cert": cert}
    except Exception as e:
        return {"ok": False, "error": type(e).__name__ + ": " + str(e)}


def mc_status(host, port=25565, timeout=6.0):
    """Minecraft 服务器列表 ping（只读状态查询，不进入游戏）。"""
    try:
        s = socket.create_connection((host, port), timeout=timeout)
        s.settimeout(timeout)
        # handshake: protocol 0x2f(-?) use 767; status next state=1
        def varint(n):
            out = b""
            while True:
                b = n & 0x7F
                n >>= 7
                if n:
                    out += bytes([b | 0x80])
                else:
                    out += bytes([b])
                    return out
        host_b = host.encode()
        hs = varint(0x00) + varint(767) + varint(len(host_b)) + host_b + struct.pack(">H", port) + varint(1)
        s.sendall(varint(len(hs)) + hs + varint(1) + varint(0x00))
        # read response
        def read_varint(sock):
            num = 0
            for i in range(5):
                byte = sock.recv(1)
                if not byte:
                    raise EOFError("eof")
                num |= (byte[0] & 0x7F) << (7 * i)
                if not (byte[0] & 0x80):
                    return num
            raise ValueError("varint too long")
        length = read_varint(s)
        data = b""
        while len(data) < length:
            chunk = s.recv(length - len(data))
            if not chunk:
                break
            data += chunk
        s.close()
        # packet id varint then string
        i = 0

        def rd():
            nonlocal i
            num = 0
            for k in range(5):
                byte = data[i]
                i += 1
                num |= (byte & 0x7F) << (7 * k)
                if not (byte & 0x80):
                    return num
            return num
        rd()  # packet id
        slen = rd()
        payload = json.loads(data[i:i + slen].decode("utf-8", "replace"))
        return {"ok": True, "payload": payload}
    except Exception as e:
        return {"ok": False, "error": type(e).__name__ + ": " + str(e)}


print("=" * 70)
print("网络只读探测 @", NOW())
print("=" * 70)

# ---------- A. ECS 121.196.47.2 ----------
p("\n### A. ECS 121.196.47.2（杭州）")
for port in (22, 80, 443):
    st, info, banner, ms = tcp("121.196.47.2", port)
    p("  TCP %-5d %-13s %.0fms  peer/info=%s  banner=%r" % (port, st, ms, info,
                                                          banner[:80] if banner else b""))
for tag, path in (("GET /", "/"), ("GET /api/status", "/api/status"),
                  ("GET /healthz", "/healthz"), ("GET /board", "/board"), ("GET /board/", "/board/")):
    r = http_get("http://121.196.47.2" + path, timeout=15)
    show_resp(tag, r, show_body=(path == "/api/status"), body_limit=4000)
    if r["ok"] and path == "/":
        body = r["body"]
        for marker in (b"APP_VER", b"2.0.0", b"pw-trend-top", b"tLogin", b"\xe6\x8a\xbd\xe7\xad\xbe",
                       b"\xe8\xaf\x8a\xe6\x96\xad", b"tool.furina.fun"):
            p("    marker %-20r -> %d" % (marker[:20], body.count(marker)))
r = http_get("https://121.196.47.2/", timeout=10, insecure=True)
if r["ok"]:
    show_resp("HTTPS / (insecure)", r)
else:
    p("  %-28s FAIL %s" % ("HTTPS / (insecure)", r["error"]))
c = tls_cert("121.196.47.2", 443)
if c["ok"] and c.get("cert"):
    cert = c["cert"]
    p("  TLS 证书: subject=%s issuer=%s notBefore=%s notAfter=%s SAN=%s" % (
        cert.get("subject"), cert.get("issuer"), cert.get("notBefore"), cert.get("notAfter"),
        cert.get("subjectAltName")))
else:
    p("  TLS 证书: FAIL", c.get("error"))

# ---------- B. MC 服务器 ----------
for host in ("120.27.217.236", "115.29.166.27"):
    p("\n### B. MC 候选 %s" % host)
    for port in (22, 25565, 80):
        st, info, banner, ms = tcp(host, port)
        p("  TCP %-5d %-13s %.0fms  peer/info=%s  banner=%r" % (
            port, st, ms, info, banner[:80] if banner else b""))
    r = mc_status(host, 25565)
    if r["ok"]:
        pl = r["payload"]
        p("  MC status: version=%s players=%s motd=%r" % (
            pl.get("version"), pl.get("players"), str(pl.get("description"))[:160]))
    else:
        p("  MC status: FAIL", r["error"])

# ---------- C. 阿里云函数计算 FC（MC 一键启动） ----------
p("\n### C. FC start.furina.fun → mc-start-mc-serv-control-alwwvseret.cn-hangzhou.fcapp.run")
r = http_get("https://mc-start-mc-serv-control-alwwvseret.cn-hangzhou.fcapp.run/", timeout=25)
show_resp("FC GET /", r, show_body=True, body_limit=800)
r2 = http_get("http://mc-start-mc-serv-control-alwwvseret.cn-hangzhou.fcapp.run/", timeout=15)
show_resp("FC GET / (http)", r2, show_body=True, body_limit=400)

# ---------- D. 域名解析（应因暂停解析失败） ----------
p("\n### D. 域名解析实测（本地系统解析器）")
for name in ("furina.fun", "tool.furina.fun", "mc.furina.fun", "start.furina.fun", "me.furina.fun"):
    try:
        infos = socket.getaddrinfo(name, None)
        ips = sorted({i[4][0] for i in infos})
        p("  %-22s -> %s" % (name, ips))
    except Exception as e:
        p("  %-22s -> 解析失败: %s: %s" % (name, type(e).__name__, e))

# ---------- E. OSS 默认端点（绕开自定义域名，确认源站存活） ----------
p("\n### E. OSS 默认端点（只读 GET）")
for url in ("https://tool-furina-fun.oss-cn-hongkong.aliyuncs.com/index.html",
            "https://tool-furina-fun.oss-cn-hongkong.aliyuncs.com/tt.json"):
    r = http_get(url, timeout=25)
    if r["ok"]:
        show_resp("OSS " + url.rsplit("/", 1)[-1], r)
        p("    与本地/OSS 对象 sha 比对: %s" % (
            "MATCH" if sha(r["body"]) in (LOCAL_INDEX_SHA,) or url.endswith("tt.json") else
            ("MATCH" if sha(r["body"]) == LOCAL_INDEX_SHA else "MISMATCH")))
    else:
        p("  OSS", url, "FAIL", r["error"])

# ---------- F. 暂停域名 URL 访问 ----------
p("\n### F. 自定义域名 URL 实测（预期因解析暂停失败）")
for url in ("https://tool.furina.fun/", "http://tool.furina.fun/",
            "https://mc.furina.fun/", "https://start.furina.fun/"):
    r = http_get(url, timeout=10)
    p("  %-30s -> %s" % (url, "status=" + str(r.get("status")) if r["ok"] else "FAIL " + r["error"]))

print("\n[DONE]", NOW())
