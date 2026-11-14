#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
自检：起一个本地 HTTPS/HTTP 源站 + 一个 pcap 代理，真实走一遍
  CONNECT/TLS/keep-alive → 抓包落盘 → show 打码 → har 脱敏 → ca.crt 下发 → replay
不联网、不碰真实账号，全部 127.0.0.1。

    python pcap/tests/selftest.py
"""
import gzip
import http.client
import json
import os
import socket
import ssl
import subprocess
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))
import pcap  # noqa: E402

FAILS = []
PASSED = 0


def check(name, cond, extra=""):
    global PASSED
    if cond:
        PASSED += 1
        print(f"  ok   {name}")
    else:
        FAILS.append(name)
        print(f"  FAIL {name}  {extra}")


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def wait_port(port, timeout=20):
    end = time.time() + timeout
    while time.time() < end:
        try:
            with socket.create_connection(("127.0.0.1", port), 0.3):
                return True
        except OSError:
            time.sleep(0.1)
    return False


# --------------------------------------------------------------------------
# 源站
# --------------------------------------------------------------------------
class Origin(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype="application/json", extra=None):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        for k, v in (extra or []):
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def do_GET(self):
        p = self.path.split("?")[0]
        if p == "/api/list":
            self._send(200, json.dumps(
                {"code": 0, "data": [{"id": 1, "name": "活动A", "quota": 30}]},
                ensure_ascii=False).encode())
        elif p == "/api/gz":
            raw = json.dumps({"gz": True, "text": "压缩过的响应"}, ensure_ascii=False).encode()
            self._send(200, gzip.compress(raw), extra=[("Content-Encoding", "gzip")])
        elif p == "/api/chunked":
            data = json.dumps({"chunk": True}, ensure_ascii=False).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Transfer-Encoding", "chunked")
            self.end_headers()
            self.wfile.write(b"%x\r\n" % len(data) + data + b"\r\n0\r\n\r\n")
            self.wfile.flush()
        else:
            self._send(404, b'{"code":404}')

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(n)
        try:
            body = json.loads(raw or b"{}")
        except Exception:
            body = {}
        self._send(200, json.dumps(
            {"code": 0, "ok": True, "echo": body, "signupId": 9001},
            ensure_ascii=False).encode())


def make_origin_cert(tmp: Path):
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from datetime import datetime, timedelta, timezone

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    now = datetime.now(timezone.utc)
    name = x509.Name([x509.NameAttribute(x509.oid.NameOID.COMMON_NAME, "127.0.0.1")])
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name)
            .public_key(key.public_key()).serial_number(x509.random_serial_number())
            .not_valid_before(now - timedelta(days=1))
            .not_valid_after(now + timedelta(days=30))
            .add_extension(x509.SubjectAlternativeName([x509.IPAddress(
                __import__("ipaddress").ip_address("127.0.0.1"))]), critical=False)
            .sign(key, hashes.SHA256()))
    c, k = tmp / "origin.crt", tmp / "origin.key"
    c.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    k.write_bytes(key.private_bytes(serialization.Encoding.PEM,
                                    serialization.PrivateFormat.PKCS8,
                                    serialization.NoEncryption()))
    return c, k


def start_origin(tls_cert=None):
    srv = ThreadingHTTPServer(("127.0.0.1", 0), Origin)
    srv.daemon_threads = True
    if tls_cert:
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(str(tls_cert[0]), str(tls_cert[1]))
        srv.socket = ctx.wrap_socket(srv.socket, server_side=True)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, srv.server_address[1]


def start_mini_proxy():
    """最小 HTTP 代理：CONNECT 隧道 + 绝对 URI 转发。用来测 --upstream-proxy 链式。"""
    import socket as _s
    from urllib.parse import urlsplit

    srv = _s.socket(_s.AF_INET, _s.SOCK_STREAM)
    srv.setsockopt(_s.SOL_SOCKET, _s.SO_REUSEADDR, 1)
    srv.bind(("127.0.0.1", 0))
    srv.listen(50)
    port = srv.getsockname()[1]
    seen = []

    def relay(a, b, initial):
        if initial:
            b.sendall(initial)

        def pump(src, dst):
            try:
                while True:
                    d = src.recv(65536)
                    if not d:
                        break
                    dst.sendall(d)
            except OSError:
                pass
            finally:
                try:
                    dst.shutdown(_s.SHUT_WR)
                except Exception:
                    pass

        t = threading.Thread(target=pump, args=(a, b), daemon=True)
        t.start()
        pump(b, a)
        t.join(timeout=3)

    def handle(c):
        try:
            buf = b""
            while b"\r\n\r\n" not in buf:
                d = c.recv(4096)
                if not d:
                    return
                buf += d
            head, leftover = buf.split(b"\r\n\r\n", 1)
            head = head.decode("latin-1")
            first = head.split("\r\n")[0]
            method, target = first.split()[0], first.split()[1]
            seen.append(target)
            if method.upper() == "CONNECT":
                h, p = target.rsplit(":", 1)
                up = _s.create_connection((h, int(p)), 10)
                c.sendall(b"HTTP/1.1 200 Connection established\r\n\r\n")
                relay(c, up, leftover)
                up.close()
            else:
                u = urlsplit(target)
                up = _s.create_connection((u.hostname, u.port or 80), 10)
                path = (u.path or "/") + (("?" + u.query) if u.query else "")
                lines = head.split("\r\n")
                lines[0] = f"{method} {path} HTTP/1.1"
                up.sendall(("\r\n".join(lines) + "\r\n\r\n").encode("latin-1") + leftover)
                relay(c, up, b"")
                up.close()
        except Exception:
            pass
        finally:
            try:
                c.close()
            except Exception:
                pass

    def loop():
        while True:
            try:
                c, _ = srv.accept()
            except OSError:
                return
            threading.Thread(target=handle, args=(c,), daemon=True).start()

    threading.Thread(target=loop, daemon=True).start()
    return srv, port, seen


# --------------------------------------------------------------------------
def main():
    tmp = Path(tempfile.mkdtemp(prefix="pcap_selftest_"))
    env = dict(os.environ, PCAP_HOME=str(tmp), PYTHONIOENCODING="utf-8")
    proxy_port = free_port()

    cert = make_origin_cert(tmp)
    tls_srv, tls_port = start_origin(cert)
    http_srv, http_port = start_origin(None)

    log = open(tmp / "proxy.log", "wb")
    proc = subprocess.Popen(
        [sys.executable, str(ROOT / "pcap.py"), "run", "--bind", "127.0.0.1",
         "--port", str(proxy_port), "--insecure-upstream", "--timeout", "15",
         "--upstream-proxy", "off"],
        env=env, stdout=log, stderr=subprocess.STDOUT)

    try:
        check("代理端口就绪", wait_port(proxy_port), f"port={proxy_port}")
        ca = tmp / "ca" / "ca.crt"
        check("CA 已生成", ca.exists())
        ctx = ssl.create_default_context(cafile=str(ca))

        def tls_conn():
            c = http.client.HTTPSConnection("127.0.0.1", proxy_port, context=ctx, timeout=15)
            c.set_tunnel("127.0.0.1", tls_port)
            return c

        host_hdr = {"Host": f"127.0.0.1:{tls_port}", "Authorization": "Bearer SECRET123"}

        # 1) GET
        c = tls_conn()
        c.request("GET", "/api/list", headers=dict(host_hdr))
        r = c.getresponse()
        body = r.read()
        check("GET 200", r.status == 200, str(r.status))
        check("GET 内容正确", "活动A".encode() in body)
        c.close()

        # 2) POST JSON（同一代理连接复用）
        c = tls_conn()
        c.request("POST", "/api/signup", body=json.dumps(
            {"activityId": 7, "note": "hello"}).encode(),
            headers=dict(host_hdr, **{"Content-Type": "application/json"}))
        r = c.getresponse()
        r.read()
        check("POST 200", r.status == 200, str(r.status))
        c.close()

        # 3) gzip
        c = tls_conn()
        c.request("GET", "/api/gz", headers=dict(host_hdr))
        r = c.getresponse()
        gz = r.read()
        check("gzip 透明（客户端仍收到压缩体）", gz[:2] == b"\x1f\x8b")
        c.close()

        # 4) chunked
        c = tls_conn()
        c.request("GET", "/api/chunked", headers=dict(host_hdr))
        r = c.getresponse()
        chunk_body = r.read()
        check("chunked 解出正文", b"chunk" in chunk_body, chunk_body[:60])
        c.close()

        # 5) 普通 HTTP 代理
        hc = http.client.HTTPConnection("127.0.0.1", proxy_port, timeout=15)
        hc.request("GET", f"http://127.0.0.1:{http_port}/api/list")
        hr = hc.getresponse()
        hb = hr.read()
        check("HTTP 明文代理 200", hr.status == 200 and "活动A".encode() in hb, str(hr.status))
        hc.close()

        # 6) CA 下载页（经代理，明文）
        hc = http.client.HTTPConnection("127.0.0.1", proxy_port, timeout=15)
        hc.request("GET", "http://pcap.local/ca.crt")
        cr = hc.getresponse()
        pem = cr.read()
        check("ca.crt 可下载", cr.status == 200 and b"BEGIN CERTIFICATE" in pem, str(cr.status))
        hc.close()

        hc = http.client.HTTPConnection("127.0.0.1", proxy_port, timeout=15)
        hc.request("GET", "http://pcap.local/")
        pr = hc.getresponse()
        page = pr.read()
        check("说明页可打开", pr.status == 200 and b"CA" in page, str(pr.status))
        hc.close()

        time.sleep(0.6)
        capdir = tmp / "captures"
        sessions = [d for d in capdir.iterdir() if d.is_dir()]
        check("生成会话目录", len(sessions) == 1, str(sessions))
        session = sessions[0]
        recs = []
        for p in sorted(session.glob("*.json")):
            if p.name != "meta.json":
                recs.append(json.loads(p.read_text(encoding="utf-8")))
        check("落盘条数 >= 5", len(recs) >= 5, f"got {len(recs)}")

        def find(sub):
            for x in recs:
                if sub in x["url"]:
                    return x
            return None

        lst = find("/api/list")
        check("记录到 GET 列表", lst is not None and lst["status"] == 200)
        check("URL 完整", lst and lst["url"].endswith("/api/list"), lst and lst["url"])
        check("请求头原样保留（含 token）",
              lst and any("SECRET123" in v for k, v in lst["req_headers"]),
              "")
        check("耗时已记录", lst and lst["ms"] > 0)

        sg = find("/api/signup")
        check("记录到 POST 报名", sg is not None and sg["method"] == "POST")
        check("POST 请求体已保存",
              sg and sg.get("req_text") and "activityId" in sg["req_text"],
              (sg or {}).get("req_text"))
        check("POST 响应体已解析",
              sg and sg.get("resp_text") and "signupId" in sg["resp_text"])

        gzr = find("/api/gz")
        check("gzip 响应已解压入库",
              gzr and gzr.get("resp_text") and "压缩过的响应" in gzr["resp_text"],
              (gzr or {}).get("resp_text"))

        ch = find("/api/chunked")
        check("chunked 响应已解码入库",
              ch and ch.get("resp_text") and "chunk" in ch["resp_text"])

        # show 打码
        sp = subprocess.run([sys.executable, str(ROOT / "pcap.py"), "show", lst["id"], "--full"],
                            env=env, capture_output=True, text=True, encoding="utf-8", timeout=60)
        check("show 正常退出", sp.returncode == 0, sp.stderr[:300])
        check("show 不泄露 token", "SECRET123" not in sp.stdout, sp.stdout[:300])
        check("show 有打码标记", "REDACTED" in sp.stdout)
        check("show 显示响应正文", "活动A" in sp.stdout)

        # HAR
        har_path = tmp / "out.har"
        hp = subprocess.run([sys.executable, str(ROOT / "pcap.py"), "har", "-o", str(har_path)],
                            env=env, capture_output=True, text=True, encoding="utf-8", timeout=60)
        check("har 导出成功", hp.returncode == 0 and har_path.exists(), hp.stderr[:300])
        har_text = har_path.read_text(encoding="utf-8")
        har = json.loads(har_text)
        check("HAR 是合法 JSON 且含 entries", len(har["log"]["entries"]) >= 5,
              str(len(har["log"]["entries"])))
        check("HAR 默认脱敏", "SECRET123" not in har_text and "REDACTED" in har_text)
        check("HAR 含 POST body",
              any(e["request"].get("postData") for e in har["log"]["entries"]))

        # replay GET
        rp = subprocess.run([sys.executable, str(ROOT / "pcap.py"), "replay", lst["id"],
                             "--insecure", "--show-body"],
                            env=env, capture_output=True, text=True, encoding="utf-8", timeout=60)
        check("replay GET 成功", rp.returncode == 0 and "200" in rp.stdout, rp.stdout[:200] + rp.stderr[:200])
        check("replay 拿到正文", "活动A" in rp.stdout)

        # replay 非 GET 默认拒绝
        rp2 = subprocess.run([sys.executable, str(ROOT / "pcap.py"), "replay", sg["id"]],
                             env=env, capture_output=True, text=True, encoding="utf-8", timeout=60)
        check("replay POST 未加 --send 时拒绝", rp2.returncode == 3, str(rp2.returncode))

        # 12) 老服务器弱 TLS 判定
        check("弱 DH 错误被识别",
              pcap._needs_weak_tls(Exception("[SSL: DH_KEY_TOO_SMALL] dh key too small")))
        check("普通错误不误判",
              not pcap._needs_weak_tls(Exception("certificate verify failed")))

        # list
        lp = subprocess.run([sys.executable, str(ROOT / "pcap.py"), "list"],
                            env=env, capture_output=True, text=True, encoding="utf-8", timeout=60)
        check("list 正常", lp.returncode == 0 and "/api/list" in lp.stdout, lp.stdout[:300])

        # 11) 链式上游代理：pcap -> mini http proxy -> 源站
        mini_srv, mini_port, mini_seen = start_mini_proxy()
        proxy2 = free_port()
        out2 = tmp / "captures2"
        log2 = open(tmp / "proxy2.log", "wb")
        proc2 = subprocess.Popen(
            [sys.executable, str(ROOT / "pcap.py"), "run", "--bind", "127.0.0.1",
             "--port", str(proxy2), "--insecure-upstream", "--timeout", "15",
             "--upstream-proxy", f"http://127.0.0.1:{mini_port}", "--out", str(out2)],
            env=env, stdout=log2, stderr=subprocess.STDOUT)
        try:
            check("链式代理端口就绪", wait_port(proxy2), f"port={proxy2}")
            c3 = http.client.HTTPSConnection("127.0.0.1", proxy2, context=ctx, timeout=15)
            c3.set_tunnel("127.0.0.1", tls_port)
            c3.request("GET", "/api/list", headers=dict(host_hdr))
            r3 = c3.getresponse()
            b3 = r3.read()
            c3.close()
            check("链式代理 GET 200", r3.status == 200 and "活动A".encode() in b3, str(r3.status))
            check("上游代理确实被调用", any("127.0.0.1" in s for s in mini_seen), str(mini_seen[:3]))
            time.sleep(0.5)
            recs2 = [json.loads(p.read_text(encoding="utf-8"))
                     for p in sorted(out2.glob("*.json")) if p.name != "meta.json"]
            check("链式代理已落盘", any("/api/list" in x["url"] for x in recs2), f"got {len(recs2)}")
        finally:
            proc2.terminate()
            try:
                proc2.wait(timeout=5)
            except Exception:
                proc2.kill()
            log2.close()
            try:
                mini_srv.close()
            except Exception:
                pass

    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except Exception:
            proc.kill()
        log.close()
        tls_srv.shutdown()
        http_srv.shutdown()
        print(f"\n过程文件：{tmp}")

    print()
    total = PASSED + len(FAILS)
    print(f"RESULT: {'PASS' if not FAILS else 'FAIL'}  {PASSED}/{total}")
    if FAILS:
        for f in FAILS:
            print("  -", f)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
