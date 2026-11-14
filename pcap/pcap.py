#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
pcap.py — 本机 HTTPS 抓包工具（中间人代理），用来分析微信小程序 / 公众号 H5 的接口。

只用在本机：手机或电脑把 HTTP 代理指向它，装一次它生成的 CA 证书，之后所有请求
都会被记录下来（列表 / 报名 / 详情……），可导出 HAR、可原样重放。

命令：
    python pcap.py run                 # 启动抓包（默认 0.0.0.0:8080）
    python pcap.py list                # 看抓到了什么
    python pcap.py show 12             # 看第 12 条的完整请求/响应（敏感值已打码）
    python pcap.py har -o 抓包.har     # 导出 HAR（默认脱敏）
    python pcap.py replay 12           # 重放第 12 条（非 GET 需 --send）
    python pcap.py ca                  # 证书信息 / 重新生成

依赖：cryptography（pip install cryptography）。其余全部标准库。
隐私：captures/ 与 ca/ 含 token 和私钥，已在 .gitignore；导出 HAR 默认打码。
"""
from __future__ import annotations

import argparse
import base64
import fnmatch
import gzip
import hashlib
import json
import os
import re
import socket
import ssl
import subprocess
import sys
import threading
import time
import zlib
from datetime import datetime, timedelta, timezone
from pathlib import Path

VERSION = "1.1.0"
ROOT = Path(__file__).resolve().parent
HOME = Path(os.environ.get("PCAP_HOME") or ROOT)
CA_DIR = HOME / "ca"
CA_CRT = CA_DIR / "ca.crt"
CA_KEY = CA_DIR / "ca.key"
LEAF_KEY = CA_DIR / "leaf.key"
CAP_DIR = HOME / "captures"

CRLF = b"\r\n"
HDR_END = b"\r\n\r\n"
MAX_BODY_DEFAULT = 2_000_000

# 微信/系统基础设施的噪音域名，默认不落盘（仍会正常转发）
DEFAULT_EXCLUDE = [
    "*.qpic.cn", "*.gtimg.com", "*.qlogo.cn", "*.gstatic.com", "*.googleapis.com",
    "*.apple.com", "*.icloud.com", "*.mzstatic.com", "*.doubleclick.net",
    "*.weixin.qq.com", "*.wx.qq.com", "*.wechat.com", "*.tenpay.com", "*.weiyun.com",
]

SENS_HEADERS = {
    "authorization", "proxy-authorization", "cookie", "set-cookie", "x-token",
    "token", "x-access-token", "x-auth-token", "x-session", "x-sid", "x-user-token",
    "session", "x-csrf-token", "x-xsrf-token",
}
SENS_KEYS = re.compile(
    r"(token|secret|session|ticket|sign|signature|password|passwd|pwd|"
    r"openid|unionid|phone|mobile|idcard|credential|auth)", re.I)

_print_lock = threading.Lock()
_stats_lock = threading.Lock()
_tlsinfo = threading.local()          # 每连接记录 SNI，握手失败时用
_tls_fail_seen: set = set()           # 同一 host:port 的失败只打一次


# --------------------------------------------------------------------------
# 基础工具
# --------------------------------------------------------------------------
def out(msg: str = "") -> None:
    with _print_lock:
        try:
            print(msg, flush=True)
        except UnicodeEncodeError:
            print(msg.encode("utf-8", "replace").decode("utf-8", "replace"), flush=True)


def now_local() -> datetime:
    return datetime.now().astimezone()


def iso(dt: datetime) -> str:
    return dt.isoformat(timespec="milliseconds")


def human_size(n: int) -> str:
    if n is None:
        return "-"
    if n < 1024:
        return f"{n}B"
    if n < 1024 * 1024:
        return f"{n / 1024:.1f}KB"
    return f"{n / 1024 / 1024:.2f}MB"


def split_hostport(s: str, default_port: int):
    """'a.com:443' / '[::1]:443' / 'a.com' -> (host, port)"""
    s = (s or "").strip()
    if not s:
        return "", default_port
    if s.startswith("["):
        i = s.find("]")
        host = s[1:i]
        rest = s[i + 1:]
        if rest.startswith(":"):
            try:
                return host, int(rest[1:])
            except ValueError:
                pass
        return host, default_port
    if s.count(":") == 1:
        h, p = s.split(":")
        try:
            return h, int(p)
        except ValueError:
            return h, default_port
    return s, default_port


def parse_head(head: bytes):
    """返回 (首行, [(k,v), ...])"""
    try:
        text = head.decode("latin-1")
    except Exception:
        text = head.decode("utf-8", "replace")
    lines = text.split("\r\n")
    first = lines[0] if lines else ""
    headers = []
    for ln in lines[1:]:
        if not ln:
            continue
        k, _, v = ln.partition(":")
        headers.append((k.strip(), v.strip()))
    return first, headers


def hget(headers, name: str) -> str:
    low = name.lower()
    for k, v in headers:
        if k.lower() == low:
            return v
    return ""


def hhas(headers, name: str) -> bool:
    low = name.lower()
    return any(k.lower() == low for k, _ in headers)


def host_match(host: str, patterns) -> bool:
    host = (host or "").lower()
    for p in patterns:
        p = p.strip().lower()
        if not p:
            continue
        if fnmatch.fnmatch(host, p):
            return True
        # 写 *.a.com 时也匹配裸域名 a.com
        if p.startswith("*.") and (host == p[2:] or host.endswith(p[1:])):
            return True
    return False


def mask_header_value(name: str, value: str) -> str:
    if name.lower() in SENS_HEADERS:
        return "***REDACTED***"
    return value


def mask_headers(headers):
    return [[k, mask_header_value(k, v)] for k, v in headers]


def _mask_obj(obj, depth=0):
    if depth > 12:
        return obj
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            if isinstance(k, str) and SENS_KEYS.search(k):
                out[k] = "***REDACTED***"
            else:
                out[k] = _mask_obj(v, depth + 1)
        return out
    if isinstance(obj, list):
        return [_mask_obj(x, depth + 1) for x in obj]
    return obj


def mask_json_text(text: str) -> str:
    """JSON 文本 -> 敏感键的值打码；解析失败原样返回。"""
    if not text:
        return text
    s = text.strip()
    if not (s.startswith("{") or s.startswith("[")):
        return text
    try:
        obj = json.loads(s)
    except Exception:
        return text
    return json.dumps(_mask_obj(obj), ensure_ascii=False, indent=2)


def decode_text(headers, body: bytes):
    """尽力把 body 解成文本；失败返回 None。"""
    if not body:
        return ""
    enc = hget(headers, "content-encoding").lower()
    try:
        if "gzip" in enc:
            body = gzip.decompress(body)
        elif "deflate" in enc:
            try:
                body = zlib.decompress(body)
            except zlib.error:
                body = zlib.decompress(body, -zlib.MAX_WBITS)
    except Exception:
        return None
    ctype = hget(headers, "content-type").lower()
    textual = any(x in ctype for x in ("json", "text/", "xml", "javascript", "x-www-form-urlencoded"))
    charset = "utf-8"
    m = re.search(r"charset=([\w\-]+)", ctype)
    if m:
        charset = m.group(1)
    try:
        txt = body.decode(charset, "replace")
    except Exception:
        txt = body.decode("utf-8", "replace")
    if not textual:
        # 非文本类型：只有看起来像 JSON 才认
        t = txt.lstrip()
        if not (t.startswith("{") or t.startswith("[")):
            return None
    if "json" in ctype or (txt.lstrip().startswith(("{", "[")) and textual):
        try:
            return json.dumps(json.loads(txt), ensure_ascii=False, indent=2)
        except Exception:
            return txt
    return txt


def b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii") if data else ""


def local_ips():
    ips = []
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("223.5.5.5", 80))
        ips.append(s.getsockname()[0])
        s.close()
    except Exception:
        pass
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = info[4][0]
            if ip not in ips and not ip.startswith("127."):
                ips.append(ip)
    except Exception:
        pass
    return [ip for ip in ips if not ip.startswith("169.254.")]


# --------------------------------------------------------------------------
# 证书
# --------------------------------------------------------------------------
def _require_crypto():
    try:
        from cryptography import x509  # noqa: F401
        from cryptography.hazmat.primitives import hashes, serialization  # noqa: F401
        from cryptography.hazmat.primitives.asymmetric import rsa  # noqa: F401
    except ImportError:
        out("缺少 cryptography：请先运行  pip install cryptography")
        raise SystemExit(2)


def _crypto():
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    return x509, hashes, serialization, rsa


def _write_private(path: Path, key) -> None:
    _, _, serialization, _ = _crypto()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ))
    try:
        os.chmod(path, 0o600)
    except Exception:
        pass


def ensure_ca(force: bool = False) -> None:
    _require_crypto()
    if CA_CRT.exists() and CA_KEY.exists() and not force:
        return
    x509, hashes, serialization, rsa = _crypto()
    CA_DIR.mkdir(parents=True, exist_ok=True)
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    now = datetime.now(timezone.utc)
    name = x509.Name([
        x509.NameAttribute(x509.oid.NameOID.COMMON_NAME, "pcap local CA (only this PC)"),
        x509.NameAttribute(x509.oid.NameOID.ORGANIZATION_NAME, "local debug only"),
    ])
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(days=1))
        .not_valid_after(now + timedelta(days=3650))
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .add_extension(x509.KeyUsage(
            digital_signature=True, content_commitment=False, key_encipherment=False,
            data_encipherment=False, key_agreement=False, key_cert_sign=True,
            crl_sign=True, encipher_only=False, decipher_only=False), critical=True)
        .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False)
        .sign(key, hashes.SHA256())
    )
    _write_private(CA_KEY, key)
    CA_CRT.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    out(f"已生成 CA：{CA_CRT}")


def _leaf_key():
    """所有站点证书共用一个叶子私钥，省掉每个域名 100ms 的 RSA 生成。"""
    _, _, serialization, rsa = _crypto()
    if LEAF_KEY.exists():
        try:
            from cryptography.hazmat.primitives.serialization import load_pem_private_key
            return load_pem_private_key(LEAF_KEY.read_bytes(), password=None)
        except Exception:
            pass
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    _write_private(LEAF_KEY, key)
    return key


_leaf_cache: dict[str, Path] = {}
_ctx_cache: dict[str, ssl.SSLContext] = {}
_cache_lock = threading.Lock()


def leaf_cert(host: str) -> Path:
    with _cache_lock:
        if host in _leaf_cache and _leaf_cache[host].exists():
            return _leaf_cache[host]
    x509, hashes, serialization, _ = _crypto()
    from cryptography.hazmat.primitives.serialization import load_pem_private_key

    ca_key = load_pem_private_key(CA_KEY.read_bytes(), password=None)
    ca_cert = x509.load_pem_x509_certificate(CA_CRT.read_bytes())
    safe = re.sub(r"[^A-Za-z0-9._-]", "_", host)[:80] or "unknown"
    path = CA_DIR / f"leaf_{safe}.crt"

    key = _leaf_key()
    now = datetime.now(timezone.utc)
    try:
        import ipaddress
        alt = x509.IPAddress(ipaddress.ip_address(host))
    except ValueError:
        alt = x509.DNSName(host)
    cert = (
        x509.CertificateBuilder()
        .subject_name(x509.Name([x509.NameAttribute(x509.oid.NameOID.COMMON_NAME, host[:64])]))
        .issuer_name(ca_cert.subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(days=1))
        .not_valid_after(now + timedelta(days=825))
        .add_extension(x509.SubjectAlternativeName([alt]), critical=False)
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(x509.KeyUsage(
            digital_signature=True, content_commitment=False, key_encipherment=True,
            data_encipherment=False, key_agreement=False, key_cert_sign=False,
            crl_sign=False, encipher_only=False, decipher_only=False), critical=True)
        .add_extension(x509.ExtendedKeyUsage([x509.oid.ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
        .sign(ca_key, hashes.SHA256())
    )
    path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    with _cache_lock:
        _leaf_cache[host] = path
    return path


def server_ctx_for(default_host: str) -> ssl.SSLContext:
    with _cache_lock:
        ctx = _ctx_cache.get(default_host)
        if ctx is not None:
            return ctx
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    try:
        ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    except Exception:
        pass
    ctx.set_alpn_protocols(["http/1.1"])
    ctx.load_cert_chain(str(leaf_cert(default_host)), str(LEAF_KEY))

    def _sni(sslobj, server_name, _ctx):
        _tlsinfo.sni = server_name or ""
        if not server_name or server_name == default_host:
            return
        try:
            other = server_ctx_for(server_name)
            sslobj.context = other
        except Exception:
            pass

    ctx.sni_callback = _sni
    with _cache_lock:
        _ctx_cache[default_host] = ctx
    return ctx


# --------------------------------------------------------------------------
# 读连接
# --------------------------------------------------------------------------
class Conn:
    def __init__(self, sock, initial: bytes = b""):
        self.sock = sock
        self.buf = bytearray(initial)

    def _fill(self, n: int = 65536) -> None:
        d = self.sock.recv(n)
        if not d:
            raise EOFError("closed")
        self.buf += d

    def read_until(self, delim: bytes = HDR_END, limit: int = 262144) -> bytes:
        while True:
            i = self.buf.find(delim)
            if i >= 0:
                outb = bytes(self.buf[: i + len(delim)])
                del self.buf[: i + len(delim)]
                return outb
            if len(self.buf) > limit:
                raise ValueError("head too large")
            self._fill()

    def read_exact(self, n: int) -> bytes:
        if n < 0 or n > 64 * 1024 * 1024:
            raise ValueError("body too large")
        while len(self.buf) < n:
            self._fill()
        outb = bytes(self.buf[:n])
        del self.buf[:n]
        return outb

    def read_some(self, n: int = 65536) -> bytes:
        if self.buf:
            outb = bytes(self.buf[:n])
            del self.buf[:n]
            return outb
        return self.sock.recv(n)

    def drain_buf(self) -> bytes:
        outb = bytes(self.buf)
        self.buf.clear()
        return outb


def recv_head_exact(sock, limit: int = 65536) -> bytes:
    """逐字节读到 \\r\\n\\r\\n —— 只用于 CONNECT，保证不会吃掉后面的 TLS ClientHello。"""
    buf = bytearray()
    while len(buf) < limit:
        d = sock.recv(1)
        if not d:
            return bytes(buf)
        buf += d
        if buf.endswith(HDR_END):
            return bytes(buf)
    return bytes(buf)


def read_chunked(conn: Conn, limit: int = 64 * 1024 * 1024) -> bytes:
    outb = bytearray()
    while True:
        line = conn.read_until(CRLF, 8192).strip()
        try:
            size = int(line.split(b";")[0], 16)
        except ValueError:
            raise ValueError("bad chunk size")
        if size == 0:
            while True:  # trailer
                t = conn.read_until(CRLF, 8192)
                if t in (CRLF, b""):
                    break
            return bytes(outb)
        if len(outb) + size > limit:
            raise ValueError("chunked body too large")
        outb += conn.read_exact(size)
        conn.read_exact(2)


def read_body(conn: Conn, headers, limit: int) -> bytes:
    te = hget(headers, "transfer-encoding").lower()
    if "chunked" in te:
        return read_chunked(conn, limit)
    cl = hget(headers, "content-length")
    if cl:
        try:
            n = int(cl)
        except ValueError:
            return b""
        if n > limit:
            return conn.read_exact(min(n, limit))
        return conn.read_exact(n)
    return b""


# --------------------------------------------------------------------------
# 记录
# --------------------------------------------------------------------------
class Store:
    def __init__(self, outdir: Path, cfg):
        self.dir = outdir
        self.cfg = cfg
        self.dir.mkdir(parents=True, exist_ok=True)
        self.lock = threading.Lock()
        self.seq = 0
        self.index_path = self.dir / "index.jsonl"
        self.count = 0
        self.saved = 0

    def should_store(self, host: str) -> bool:
        if self.cfg.only and not host_match(host, self.cfg.only):
            return False
        if host_match(host, self.cfg.exclude):
            return False
        return True

    def add(self, rec: dict) -> None:
        with self.lock:
            self.count += 1
            if not rec.get("stored"):
                return
            self.seq += 1
            rec["id"] = f"{self.seq:04d}"
            path = self.dir / f"{rec['id']}.json"
            path.write_text(json.dumps(rec, ensure_ascii=False, indent=1), encoding="utf-8")
            with open(self.index_path, "a", encoding="utf-8") as f:
                f.write(json.dumps({
                    "id": rec["id"], "ts": rec["ts"], "method": rec["method"],
                    "url": rec["url"], "status": rec["status"],
                    "ms": rec["ms"], "bytes": rec["resp_len"],
                }, ensure_ascii=False) + "\n")
            self.saved += 1


def make_record(cfg, store, scheme, host, port, method, path, req_headers,
                req_body, req_truncated) -> dict:
    rec = {
        "id": None,
        "ts": iso(now_local()),
        "scheme": scheme, "host": host, "port": port,
        "method": method,
        "path": path,
        "url": f"{scheme}://{host}{'' if (scheme == 'https' and port == 443) or (scheme == 'http' and port == 80) else ':' + str(port)}{path}",
        "req_headers": [[k, v] for k, v in req_headers],
        "req_len": len(req_body or b""),
        "req_truncated": bool(req_truncated),
        "req_body_b64": b64(req_body or b""),
        "req_text": None,
        "status": 0, "reason": "",
        "resp_headers": [],
        "resp_len": 0, "resp_truncated": False,
        "resp_body_b64": "", "resp_text": None,
        "ms": 0.0, "note": "",
        "stored": store.should_store(host),
    }
    if rec["stored"] and req_body:
        txt = decode_text(req_headers, req_body)
        rec["req_text"] = txt
    return rec


def record_response(store, rec, status, reason, headers, body, ms, note="", truncated=False,
                    skip_body=False):
    rec["status"] = status
    rec["reason"] = reason
    rec["resp_headers"] = [[k, v] for k, v in headers]
    rec["ms"] = round(ms, 1)
    rec["note"] = note
    rec["resp_len"] = len(body or b"")
    rec["resp_truncated"] = bool(truncated)
    if rec["stored"] and body and not skip_body:
        rec["resp_body_b64"] = b64(body)
        rec["resp_text"] = decode_text(headers, body)
    return rec


def log_line(rec: dict) -> None:
    if not rec.get("stored"):
        return
    size = human_size(rec.get("resp_len") or 0)
    ms = rec.get("ms") or 0
    note = f"  [{rec['note']}]" if rec.get("note") else ""
    line = (f"[{rec['id']}] {rec['ts'][11:19]}  {rec['method']:<6} "
            f"{rec['url'][:96]:<96} {rec['status']:>3} {size:>9} {ms:>7.0f}ms{note}")
    out(line)


def log_tls_failure(host: str, port: int, err) -> None:
    """只在第一次遇到时打印；带 SNI，方便判断是哪家域名。"""
    key = f"{host}:{port}"
    sni = getattr(_tlsinfo, "sni", "") or ""
    if key in _tls_fail_seen:
        return
    _tls_fail_seen.add(key)
    who = f"SNI={sni}" if sni else "无 SNI（客户端用 IP 直连）"
    out(f"  ! TLS 失败 {host}:{port}  {who}  {type(err).__name__}")
    if len(_tls_fail_seen) == 1:
        out("    客户端在证书校验阶段断开：要么不信任本机 CA，要么做了证书固定。")
        out("    只是图片/CDN 域名可以忽略；学校接口域名失败才需要处理。")


# --------------------------------------------------------------------------
# 上游
# --------------------------------------------------------------------------
def _proxy_url_parts(url: str):
    from urllib.parse import urlsplit, unquote
    u = urlsplit(url if "://" in url else "http://" + url)
    return (u.hostname or "127.0.0.1", u.port or 8080,
            unquote(u.username or ""), unquote(u.password or ""))


def _proxy_connect(host: str, port: int, cfg) -> socket.socket:
    """通过上游 HTTP 代理建 CONNECT 隧道，返回原始 socket。"""
    phost, pport, user, pwd = _proxy_url_parts(cfg.upstream_proxy)
    sock = socket.create_connection((phost, pport), cfg.timeout)
    sock.settimeout(cfg.timeout)
    req = f"CONNECT {host}:{port} HTTP/1.1\r\nHost: {host}:{port}\r\n"
    if user:
        cred = base64.b64encode(f"{user}:{pwd}".encode()).decode()
        req += f"Proxy-Authorization: Basic {cred}\r\n"
    sock.sendall((req + "\r\n").encode("latin-1"))
    buf = b""
    while b"\r\n\r\n" not in buf:
        d = sock.recv(4096)
        if not d:
            sock.close()
            raise OSError("上游代理提前断开")
        buf += d
        if len(buf) > 65536:
            sock.close()
            raise OSError("上游代理响应头过长")
    parts = buf.split(b"\r\n", 1)[0].split(b" ")
    try:
        code = int(parts[1])
    except Exception:
        sock.close()
        raise OSError(f"上游代理返回异常：{buf[:80]!r}")
    if code != 200:
        sock.close()
        raise OSError(f"上游代理 CONNECT 失败 {code}")
    return sock


class Upstream:
    def __init__(self, host, port, tls: bool, cfg):
        up_proxy = getattr(cfg, "upstream_proxy", None)
        if up_proxy and tls:
            self.sock = _proxy_connect(host, port, cfg)
        elif up_proxy:
            phost, pport, _, _ = _proxy_url_parts(up_proxy)
            self.sock = socket.create_connection((phost, pport), cfg.timeout)
        else:
            self.sock = socket.create_connection((host, port), cfg.timeout)
        self.sock.settimeout(cfg.timeout)
        if tls:
            ctx = ssl.create_default_context()
            try:
                ctx.set_alpn_protocols(["http/1.1"])
            except Exception:
                pass
            if cfg.insecure_upstream:
                ctx.check_hostname = False
                ctx.verify_mode = ssl.CERT_NONE
            self.sock = ctx.wrap_socket(self.sock, server_hostname=host)
        self.conn = Conn(self.sock)
        self.closed = False

    def close(self):
        self.closed = True
        try:
            self.sock.close()
        except Exception:
            pass


def request_upstream(cfg, scheme, host, port, method, path, headers, body):
    """发请求，返回 (status, reason, resp_headers, resp_body, ttfb_ms, total_ms, truncated, note)"""
    tls = scheme == "https"
    up = Upstream(host, port, tls, cfg)
    try:
        hdrs = []
        skip = {"proxy-connection", "proxy-authorization", "connection", "keep-alive",
                "te", "trailer", "upgrade", "transfer-encoding", "content-length", "host",
                "expect"}
        for k, v in headers:
            if k.lower() in skip:
                continue
            hdrs.append((k, v))
        host_hdr = hget(headers, "host") or (host if port in (80, 443) else f"{host}:{port}")
        target = path
        if getattr(cfg, "upstream_proxy", None) and scheme == "http":
            target = f"http://{host_hdr}{path}"
        head_lines = [f"{method} {target} HTTP/1.1", f"Host: {host_hdr}"]
        head_lines += [f"{k}: {v}" for k, v in hdrs]
        if body or method in ("POST", "PUT", "PATCH"):
            head_lines.append(f"Content-Length: {len(body)}")
        head_lines.append("Connection: close")
        raw = ("\r\n".join(head_lines) + "\r\n\r\n").encode("latin-1") + (body or b"")

        t0 = time.perf_counter()
        up.sock.sendall(raw)

        truncated = False
        while True:
            head = up.conn.read_until(HDR_END, 262144)
            first, resp_headers = parse_head(head)
            ttfb = (time.perf_counter() - t0) * 1000
            parts = first.split(" ", 2)
            try:
                status = int(parts[1])
            except Exception:
                raise ValueError(f"bad status line: {first[:80]}")
            reason = parts[2] if len(parts) > 2 else ""
            if 100 <= status < 200:
                continue
            break

        limit = cfg.max_body
        if method == "HEAD" or status in (204, 304):
            resp_body = b""
        elif "chunked" in hget(resp_headers, "transfer-encoding").lower():
            resp_body = read_chunked(up.conn, limit)
        elif hget(resp_headers, "content-length"):
            cl = int(hget(resp_headers, "content-length") or 0)
            if cl > limit:
                resp_body = up.conn.read_exact(limit)
                truncated = True
                # 剩余数据丢弃（连接随请求关闭）
            else:
                resp_body = up.conn.read_exact(cl)
        else:
            chunks = []
            total = 0
            while True:
                d = up.conn.read_some()
                if not d:
                    break
                total += len(d)
                if total > limit:
                    truncated = True
                    break
                chunks.append(d)
            resp_body = b"".join(chunks)
        total_ms = (time.perf_counter() - t0) * 1000
        return status, reason, resp_headers, resp_body, ttfb, total_ms, truncated, ""
    finally:
        up.close()


# --------------------------------------------------------------------------
# 响应给客户端
# --------------------------------------------------------------------------
def send_response(sock, status: int, reason: str, headers, body: bytes, is_head: bool = False):
    lines = [f"HTTP/1.1 {status} {reason}".rstrip()]
    for k, v in headers:
        if k.lower() in ("content-length", "transfer-encoding", "connection", "keep-alive"):
            continue
        lines.append(f"{k}: {v}")
    if status not in (204, 304) and not is_head:
        lines.append(f"Content-Length: {len(body)}")
    lines.append("Connection: keep-alive")
    sock.sendall(("\r\n".join(lines) + "\r\n\r\n").encode("latin-1") + (b"" if is_head else body))


def send_error(sock, status=502, msg="proxy error"):
    body = json.dumps({"ok": False, "proxy_error": msg}, ensure_ascii=False).encode()
    send_response(sock, status, "Bad Gateway", [("Content-Type", "application/json")], body)


# --------------------------------------------------------------------------
# 本地页面 / CA 下载
# --------------------------------------------------------------------------
def ca_page(ip_list, port) -> bytes:
    ips = "".join(f"<li><code>{ip}:{port}</code></li>" for ip in ip_list)
    html = f"""<!doctype html><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>抓包证书安装</title>
<style>body{{font:16px/1.7 -apple-system,system-ui,sans-serif;margin:0;padding:24px;background:#f7f8f8;color:#1f2933}}
h1{{font-size:19px;margin:0 0 12px}} .c{{max-width:520px;margin:0 auto;background:#fff;border-radius:16px;padding:20px 22px}}
a.b{{display:block;text-align:center;background:#4e9082;color:#fff;text-decoration:none;padding:14px;border-radius:12px;margin:16px 0;font-weight:600}}
code{{background:#eef2f1;padding:2px 6px;border-radius:6px}} li{{margin:4px 0}}
p{{margin:10px 0}} .m{{color:#6b7280;font-size:14px}}</style>
<div class="c"><h1>抓包证书（只装在这台手机）</h1>
<a class="b" href="/ca.crt">下载 CA 证书</a>
<p><b>iPhone</b>：Safari 打开本页 → 下载 → 设置 → 已下载描述文件 → 安装 →
<b>设置 → 通用 → 关于本机 → 证书信任设置 → 打开对该证书的完全信任</b>。</p>
<p><b>安卓</b>：下载 .crt → 设置 → 安全 → 加密与凭据 → 安装证书 → CA 证书。
<span class="m">（Android 7+ 部分 App 不信任用户证书，微信可能抓不到，优先用 iPhone。）</span></p>
<p class="m">代理地址（本机网卡）：</p><ul>{ips}</ul>
<p class="m">不用了就到「设置 → 通用 → 关于本机 → 证书信任设置」关掉，或删除描述文件。</p>
</div>"""
    return html.encode("utf-8")


def serve_local_http(sock, method, path, headers) -> bool:
    """处理 /ca.crt 与说明页；返回 True 表示已处理。"""
    if path.startswith("/ca.crt") or path.startswith("/ca.pem") or path.startswith("/ca.cer"):
        data = CA_CRT.read_bytes()
        send_response(sock, 200, "OK", [
            ("Content-Type", "application/x-x509-ca-cert"),
            ("Content-Disposition", 'attachment; filename="pcap-ca.crt"'),
        ], data if method != "HEAD" else b"", is_head=(method == "HEAD"))
        return True
    host = hget(headers, "host").lower()
    if path in ("/", "/index.html") and host.startswith("pcap"):
        data = ca_page(local_ips(), 8080)
        send_response(sock, 200, "OK", [("Content-Type", "text/html; charset=utf-8")], data)
        return True
    return False


# --------------------------------------------------------------------------
# 主流程
# --------------------------------------------------------------------------
def handle_tunnel(tls, host_hint: str, port_hint: int, cfg, store: Store):
    conn = Conn(tls)
    tls.settimeout(cfg.timeout)
    while True:
        try:
            head = conn.read_until(HDR_END, 262144)
        except (EOFError, OSError, ssl.SSLError, ValueError):
            return
        if not head:
            return
        first, headers = parse_head(head)
        parts = first.split()
        if len(parts) < 2:
            return
        method, target = parts[0].upper(), parts[1]

        host, port, path = host_hint, port_hint, target
        if target.startswith("http://") or target.startswith("https://"):
            from urllib.parse import urlsplit
            u = urlsplit(target)
            host, port = u.hostname or host_hint, u.port or port_hint
            path = (u.path or "/") + (("?" + u.query) if u.query else "")
        else:
            h = hget(headers, "host")
            if h:
                host, port = split_hostport(h, port_hint)

        # 100-continue
        if hget(headers, "expect").lower() == "100-continue":
            try:
                tls.sendall(b"HTTP/1.1 100 Continue\r\n\r\n")
            except OSError:
                return

        truncated = False
        try:
            body = read_body(conn, headers, cfg.max_len if hasattr(cfg, "max_len") else 64 * 1024 * 1024)
        except (EOFError, OSError, ValueError):
            body = b""
            truncated = True

        rec = make_record(cfg, store, "https", host, port, method, path, headers, body, truncated)
        if not rec["stored"]:
            # 不落盘也要转发
            pass

        # WebSocket / Upgrade：握手成功后盲转发
        if hhas(headers, "upgrade"):
            if _handle_upgrade(tls, conn, cfg, host, port, method, path, headers, rec, store):
                return
            continue

        t_req = time.perf_counter()
        try:
            status, reason, rh, rb, ttfb, total_ms, rtrunc, note = request_upstream(
                cfg, "https", host, port, method, path, headers, body)
        except Exception as e:
            rec["status"] = 502
            rec["ms"] = round((time.perf_counter() - t_req) * 1000, 1)
            rec["note"] = f"upstream: {type(e).__name__}: {e}"[:160]
            if rec["stored"]:
                store.add(rec)
                log_line(rec)
            try:
                send_error(tls, 502, f"{type(e).__name__}: {e}")
            except OSError:
                return
            continue

        ctype = hget(rh, "content-type").lower()
        skip_body = cfg.no_images and ctype.startswith("image/")
        record_response(store, rec, status, reason, rh, rb, total_ms, note,
                        truncated=rtrunc, skip_body=skip_body)
        if skip_body:
            rec["note"] = (rec["note"] + " image-skipped").strip()
        if rec["stored"]:
            store.add(rec)
            log_line(rec)

        try:
            send_response(tls, status, reason, rh, rb, is_head=(method == "HEAD"))
        except (OSError, ssl.SSLError):
            return


def _handle_upgrade(tls, conn, cfg, host, port, method, path, headers, rec, store) -> bool:
    """WebSocket：转发握手，101 后双向盲转发。返回 True 表示连接已结束。"""
    try:
        up = Upstream(host, port, True, cfg)
    except Exception as e:
        rec["status"] = 502
        rec["note"] = f"upgrade upstream: {e}"[:120]
        if rec["stored"]:
            store.add(rec)
            log_line(rec)
        send_error(tls, 502, "ws upstream failed")
        return False
    try:
        lines = [f"{method} {path} HTTP/1.1"]
        for k, v in headers:
            if k.lower() in ("proxy-connection", "proxy-authorization"):
                continue
            lines.append(f"{k}: {v}")
        up.sock.sendall(("\r\n".join(lines) + "\r\n\r\n").encode("latin-1"))
        head = up.conn.read_until(HDR_END, 65536)
        first, rh = parse_head(head)
        status = int(first.split()[1]) if len(first.split()) > 1 else 0
        if status != 101:
            send_response(tls, status, "", rh, b"")
            rec["status"] = status
            if rec["stored"]:
                store.add(rec)
                log_line(rec)
            up.close()
            return False
        tls.sendall(head)
        leftover = up.conn.drain_buf()
        if leftover:
            tls.sendall(leftover)
        client_left = conn.drain_buf()
        if client_left:
            up.sock.sendall(client_left)
        rec["status"] = 101
        rec["note"] = "websocket"
        rec["ms"] = 0.0
        if rec["stored"]:
            store.add(rec)
            log_line(rec)

        def pump(src, dst, first=b""):
            try:
                if first:
                    dst.sendall(first)
                while True:
                    d = src.recv(65536)
                    if not d:
                        break
                    dst.sendall(d)
            except OSError:
                pass
            finally:
                try:
                    dst.shutdown(socket.SHUT_WR)
                except Exception:
                    pass

        t1 = threading.Thread(target=pump, args=(tls, up.sock), daemon=True)
        t2 = threading.Thread(target=pump, args=(up.sock, tls), daemon=True)
        t1.start(); t2.start()
        t1.join(); t2.join()
        up.close()
        return True
    except Exception:
        up.close()
        return True


def handle_client(client, addr, cfg, store: Store):
    client.settimeout(cfg.timeout)
    try:
        head = recv_head_exact(client)
        if not head:
            return
        first, headers = parse_head(head)
        parts = first.split()
        if len(parts) < 2:
            return
        method, target = parts[0].upper(), parts[1]

        if method == "CONNECT":
            host, port = split_hostport(target, 443)
            try:
                client.sendall(b"HTTP/1.1 200 Connection established\r\n\r\n")
            except OSError:
                return
            # 客户端收到 200 才会发 ClientHello；这里短超时窥探首字节，判断是不是 TLS
            try:
                client.settimeout(min(5.0, cfg.timeout))
                peek = client.recv(1, socket.MSG_PEEK)
            except OSError:
                return
            finally:
                client.settimeout(cfg.timeout)
            if not peek:
                return
            if peek[0] != 0x16:  # 不是 TLS 握手：当裸 TCP 隧道
                _blind_tunnel(client, host, port, cfg)
                return
            try:
                ctx = server_ctx_for(host)
                tls = ctx.wrap_socket(client, server_side=True)
            except (ssl.SSLError, OSError) as e:
                log_tls_failure(host, port, e)
                return
            handle_tunnel(tls, host, port, cfg, store)
            return

        # 普通 HTTP 代理请求（绝对 URL）
        from urllib.parse import urlsplit
        if target.startswith("http://") or target.startswith("https://"):
            u = urlsplit(target)
            host, port = u.hostname or "", u.port or (443 if u.scheme == "https" else 80)
            path = (u.path or "/") + (("?" + u.query) if u.query else "")
            scheme = u.scheme
        else:
            return
        if serve_local_http(client, method, path, headers):
            return
        conn = Conn(client)
        body = read_body(conn, headers, 64 * 1024 * 1024)
        rec = make_record(cfg, store, scheme, host, port, method, path, headers, body, False)
        t_req = time.perf_counter()
        try:
            status, reason, rh, rb, ttfb, total_ms, rtrunc, note = request_upstream(
                cfg, scheme, host, port, method, path, headers, body)
        except Exception as e:
            rec["status"] = 502
            rec["ms"] = round((time.perf_counter() - t_req) * 1000, 1)
            rec["note"] = f"upstream: {type(e).__name__}: {e}"[:160]
            if rec["stored"]:
                store.add(rec)
                log_line(rec)
            send_error(client, 502, str(e))
            return
        record_response(store, rec, status, reason, rh, rb, total_ms, note, truncated=rtrunc)
        if rec["stored"]:
            store.add(rec)
            log_line(rec)
        send_response(client, status, reason, rh, rb, is_head=(method == "HEAD"))
    except (EOFError, OSError, ssl.SSLError, ValueError):
        pass
    finally:
        try:
            client.close()
        except Exception:
            pass


def _blind_tunnel(client, host, port, cfg):
    try:
        up = socket.create_connection((host, port), cfg.timeout)
    except Exception:
        return

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
                dst.shutdown(socket.SHUT_WR)
            except Exception:
                pass

    t1 = threading.Thread(target=pump, args=(client, up), daemon=True)
    t2 = threading.Thread(target=pump, args=(up, client), daemon=True)
    t1.start(); t2.start()
    t1.join(); t2.join()
    try:
        up.close()
    except Exception:
        pass


def detect_system_proxy():
    """读 Windows「Internet 选项」里的代理；没有就返回 None。"""
    if sys.platform != "win32":
        return None
    try:
        import winreg
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                             r"Software\Microsoft\Windows\CurrentVersion\Internet Settings")
        enabled = winreg.QueryValueEx(key, "ProxyEnable")[0]
        server = winreg.QueryValueEx(key, "ProxyServer")[0]
    except Exception:
        return None
    if not enabled or not server:
        return None
    server = str(server).strip()
    if "=" in server:  # http=127.0.0.1:7890;https=...
        parts = {}
        for item in server.split(";"):
            if "=" in item:
                k, v = item.split("=", 1)
                parts[k.strip().lower()] = v.strip()
        server = parts.get("https") or parts.get("http") or ""
    if not server:
        return None
    if "://" not in server:
        server = "http://" + server
    return server


def resolve_upstream(value: str):
    """'auto' -> 系统代理；'' -> 不用；其它按原样。返回 (url|None, 说明)。"""
    if value in (None, "", "off", "none"):
        return None, ""
    if value == "auto":
        found = detect_system_proxy()
        if not found:
            return None, "auto：没检测到系统代理，走直连"
        return found, f"auto：{found}"
    return (value if "://" in value else "http://" + value), ""


def cmd_run(args) -> int:
    ensure_ca()
    up_proxy, up_note = resolve_upstream(args.upstream_proxy)
    if up_proxy:
        from urllib.parse import urlsplit
        u = urlsplit(up_proxy)
        if u.port and u.port == args.port and (u.hostname or "") in ("127.0.0.1", "localhost", args.bind):
            out(f"上游代理和本机监听端口相同（{args.port}），会自己连自己，已忽略。")
            up_proxy, up_note = None, ""
    cfg = argparse.Namespace(
        timeout=args.timeout,
        max_body=int(args.max_body),
        only=[x for x in (args.only or "").split(",") if x.strip()],
        exclude=[] if args.keep_wechat else list(DEFAULT_EXCLUDE),
        no_images=not args.save_images,
        insecure_upstream=args.insecure_upstream,
        upstream_proxy=up_proxy,
        max_len=64 * 1024 * 1024,
    )
    if args.exclude:
        cfg.exclude += [x for x in args.exclude.split(",") if x.strip()]

    session = now_local().strftime("%Y%m%d-%H%M%S")
    outdir = Path(args.out) if args.out else (CAP_DIR / session)
    store = Store(outdir, cfg)
    (outdir / "meta.json").write_text(json.dumps({
        "started": iso(now_local()), "version": VERSION,
        "bind": args.bind, "port": args.port, "only": cfg.only, "exclude": cfg.exclude,
        "upstream_proxy": cfg.upstream_proxy,
    }, ensure_ascii=False, indent=1), encoding="utf-8")

    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        srv.bind((args.bind, args.port))
    except OSError as e:
        out(f"监听失败 {args.bind}:{args.port} — {e}")
        out(f"端口被占用？换一个：--port {args.port + 1}")
        return 2
    srv.listen(128)

    ips = local_ips() if args.bind in ("0.0.0.0", "") else [args.bind]
    out("")
    out(f"抓包已启动  pcap.py v{VERSION}")
    out(f"  本机        http://127.0.0.1:{args.port}/")
    for i, ip in enumerate(ips):
        if i == 0:
            out(f"  局域网      {ip}:{args.port}    ← 手机 Wi-Fi 代理填这个")
        else:
            out(f"  其它网卡    {ip}:{args.port}    （虚拟网卡，一般不用）")
    out(f"  证书页      http://pcap.local:{args.port}/     （或 /ca.crt 直接下载）")
    out(f"  只看        {', '.join(cfg.only) if cfg.only else '全部域名'}"
        f"{'（已排除微信/系统噪音域名，--keep-wechat 可关）' if not args.keep_wechat else ''}")
    out(f"  输出        {outdir}")
    if up_proxy:
        out(f"  上游代理    {up_proxy}{('  ' + up_note) if up_note else ''}")
    out("")
    out("手机步骤：1) Wi-Fi 代理 → 上面的 IP:端口   2) 浏览器开证书页装 CA")
    out("          iOS 还要：设置→通用→关于本机→证书信任设置→完全信任")
    if sys.platform == "win32":
        out("PC 微信：先 python pcap\\pcap.py trust，再按 python pcap\\pcap.py pc 配 Proxifier")
    out("")
    out("Ctrl+C 停止")
    out("")

    sem = threading.BoundedSemaphore(64)

    def worker(c, a):
        try:
            with sem:
                handle_client(c, a, cfg, store)
        except Exception as e:
            out(f"  ! 连接处理异常 {a}: {type(e).__name__}: {e}")
        finally:
            try:
                c.close()
            except Exception:
                pass

    try:
        while True:
            c, a = srv.accept()
            threading.Thread(target=worker, args=(c, a), daemon=True).start()
    except KeyboardInterrupt:
        out("")
        out(f"已停止：共 {store.count} 个请求，落盘 {store.saved} 条 → {outdir}")
    finally:
        try:
            srv.close()
        except Exception:
            pass
    return 0


# --------------------------------------------------------------------------
# 查询 / 导出 / 重放
# --------------------------------------------------------------------------
def resolve_session(name: str | None, out_dir: str | None = None) -> Path:
    base = Path(out_dir) if out_dir else CAP_DIR
    if not base.exists():
        raise SystemExit(f"还没有抓包记录：{base}")
    if name and name not in ("latest", ""):
        p = base / name
        if p.exists():
            return p
        cands = [d for d in base.iterdir() if d.is_dir() and d.name.startswith(name)]
        if len(cands) == 1:
            return cands[0]
        raise SystemExit(f"找不到会话：{name}")
    dirs = [d for d in base.iterdir() if d.is_dir() and (d / "index.jsonl").exists()]
    if not dirs:
        raise SystemExit(f"还没有抓包记录：{base}")
    return max(dirs, key=lambda d: d.stat().st_mtime)


def load_records(session: Path):
    recs = []
    for p in sorted(session.glob("*.json")):
        if p.name in ("meta.json",):
            continue
        try:
            recs.append(json.loads(p.read_text(encoding="utf-8")))
        except Exception:
            pass
    return recs


def find_record(session: Path, rid: str) -> dict:
    p = session / f"{int(rid):04d}.json"
    if p.exists():
        return json.loads(p.read_text(encoding="utf-8"))
    matches = [r for r in load_records(session) if r.get("id") == rid]
    if not matches:
        raise SystemExit(f"会话里没有 id={rid}")
    return matches[0]


def cmd_list(args) -> int:
    session = resolve_session(args.session, args.out)
    recs = load_records(session)
    out(f"会话 {session.name}  共 {len(recs)} 条")
    out("")
    out(f"{'ID':<6}{'时间':<10}{'方法':<7}{'状态':<5}{'大小':>9}  {'耗时':>8}  地址")
    for r in recs:
        out(f"{r['id']:<6}{r['ts'][11:19]:<10}{r['method']:<7}{r['status']:<5}"
            f"{human_size(r.get('resp_len') or 0):>9}  {(r.get('ms') or 0):>6.0f}ms  {r['url'][:120]}")
    return 0


def cmd_show(args) -> int:
    session = resolve_session(args.session, args.out)
    r = find_record(session, args.id)
    out("")
    out(f"[{r['id']}] {r['method']} {r['url']}")
    out(f"时间 {r['ts']}   状态 {r['status']} {r.get('reason','')}   "
        f"耗时 {r.get('ms',0):.0f}ms   请求 {human_size(r.get('req_len') or 0)} / 响应 {human_size(r.get('resp_len') or 0)}")
    if r.get("note"):
        out(f"备注 {r['note']}")
    out("")
    out("--- 请求头 ---")
    for k, v in mask_headers(r.get("req_headers") or []):
        out(f"  {k}: {v}")
    if r.get("req_text"):
        out("--- 请求体 ---")
        text = mask_json_text(r["req_text"])
        out(_clip(text, args.full))
    out("--- 响应头 ---")
    for k, v in mask_headers(r.get("resp_headers") or []):
        out(f"  {k}: {v}")
    if r.get("resp_text"):
        out("--- 响应体 ---")
        out(_clip(mask_json_text(r["resp_text"]), args.full))
    elif r.get("resp_body_b64") and r.get("resp_len"):
        out(f"--- 响应体：{human_size(r['resp_len'])} 二进制（--raw 可看 base64）---")
    if args.raw:
        out("--- 原始 base64 ---")
        out(f"请求 {r.get('req_body_b64','')[:2000]}")
        out(f"响应 {r.get('resp_body_b64','')[:8000]}")
    return 0


def _clip(text: str, full: bool) -> str:
    if not text:
        return ""
    if full or len(text) <= 4000:
        return text
    return text[:4000] + f"\n…（共 {len(text)} 字符，--full 看全部）"


def cmd_har(args) -> int:
    session = resolve_session(args.session, args.out)
    recs = load_records(session)
    entries = []
    for r in recs:
        redact = not args.no_redact
        req_headers = r.get("req_headers") or []
        resp_headers = r.get("resp_headers") or []
        if redact:
            req_headers = mask_headers(req_headers)
            resp_headers = mask_headers(resp_headers)
        post = None
        if r.get("req_text"):
            text = mask_json_text(r["req_text"]) if redact else r["req_text"]
            post = {"mimeType": hget(req_headers, "content-type") or "application/json", "text": text}
        elif r.get("req_body_b64"):
            post = {"mimeType": hget(req_headers, "content-type") or "application/octet-stream",
                    "text": r["req_body_b64"], "encoding": "base64"}
        content = {"size": r.get("resp_len") or 0,
                   "mimeType": hget(resp_headers, "content-type") or ""}
        if r.get("resp_text") is not None:
            text = mask_json_text(r["resp_text"]) if redact else r["resp_text"]
            content["text"] = text
        elif r.get("resp_body_b64"):
            content["text"] = r["resp_body_b64"]
            content["encoding"] = "base64"
        entry = {
            "startedDateTime": r["ts"],
            "time": r.get("ms") or 0,
            "request": {
                "method": r["method"], "url": r["url"], "httpVersion": "HTTP/1.1",
                "cookies": [], "headers": [{"name": k, "value": v} for k, v in req_headers],
                "queryString": [],
                "headersSize": -1, "bodySize": r.get("req_len") or 0,
            },
            "response": {
                "status": r.get("status") or 0, "statusText": r.get("reason", ""),
                "httpVersion": "HTTP/1.1", "cookies": [],
                "headers": [{"name": k, "value": v} for k, v in resp_headers],
                "content": content, "redirectURL": r.get("note", ""),
                "headersSize": -1, "bodySize": r.get("resp_len") or 0,
            },
            "cache": {},
            "timings": {"send": 0, "wait": r.get("ms") or 0, "receive": 0},
        }
        if post:
            entry["request"]["postData"] = post
        entries.append(entry)
    har = {"log": {"version": "1.2",
                   "creator": {"name": "pcap.py", "version": VERSION},
                   "pages": [], "entries": entries}}
    outp = Path(args.output) if args.output else (session / f"{session.name}.har")
    outp.write_text(json.dumps(har, ensure_ascii=False, indent=1), encoding="utf-8")
    out(f"已导出 {outp}  ({len(entries)} 条{'，敏感头/字段已打码' if not args.no_redact else '，未脱敏'})")
    if not args.no_redact:
        out("这个文件可以直接发给别人分析接口结构（token 已替换成 ***REDACTED***）。")
    return 0


def cmd_replay(args) -> int:
    session = resolve_session(args.session, args.out)
    r = find_record(session, args.id)
    method = r["method"]
    if method != "GET" and not args.send:
        out(f"这是一条 {method} 请求，重放会真的提交。确认无误后加 --send 执行：")
        out(f"  {method} {r['url']}")
        if r.get("req_text"):
            out(_clip(mask_json_text(r["req_text"]), False))
        return 3
    from urllib.parse import urlsplit
    u = urlsplit(r["url"])
    host = u.hostname or r["host"]
    port = u.port or (443 if u.scheme == "https" else 80)
    path = (u.path or "/") + (("?" + u.query) if u.query else "")
    body = base64.b64decode(r["req_body_b64"]) if r.get("req_body_b64") else b""
    cfg = argparse.Namespace(timeout=args.timeout, max_body=2_000_000,
                             insecure_upstream=args.insecure,
                             upstream_proxy=resolve_upstream(args.upstream_proxy)[0])
    repeat = max(1, args.repeat)
    for i in range(repeat):
        try:
            status, reason, rh, rb, ttfb, total, trunc, note = request_upstream(
                cfg, u.scheme, host, port, method, path, r.get("req_headers") or [], body)
        except Exception as e:
            out(f"重放失败：{type(e).__name__}: {e}")
            return 1
        out(f"#{i+1}  {status} {reason}  {human_size(len(rb))}  首字节 {ttfb:.0f}ms  总计 {total:.0f}ms")
        if args.show_body:
            text = decode_text(rh, rb)
            out(_clip(text or base64.b64encode(rb).decode(), False))
    return 0


def cmd_ca(args) -> int:
    if args.regen:
        ensure_ca(force=True)
    if not CA_CRT.exists():
        ensure_ca()
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes
    cert = x509.load_pem_x509_certificate(CA_CRT.read_bytes())
    fp = cert.fingerprint(hashes.SHA256()).hex()
    out("")
    out(f"CA 证书  {CA_CRT}")
    out(f"CA 私钥  {CA_KEY}   （绝不外传、不入库）")
    out(f"指纹     {' '.join(fp[i:i+2] for i in range(0, len(fp), 2))}")
    out(f"有效期   至 {cert.not_valid_after_utc.astimezone().date()}")
    out("")
    out("装到手机上才会被信任：手机代理指向本机端口 → 浏览器打开 http://pcap.local:8080/ca.crt")
    return 0


# --------------------------------------------------------------------------
# Windows 根证书 / PC 微信引导
# --------------------------------------------------------------------------
def cert_sha1() -> str:
    """证书 DER 的 SHA1（certutil 用它定位/删除证书）。"""
    from cryptography import x509
    from cryptography.hazmat.primitives import serialization
    cert = x509.load_pem_x509_certificate(CA_CRT.read_bytes())
    der = cert.public_bytes(serialization.Encoding.DER)
    return hashlib.sha1(der).hexdigest().upper()


def _run(cmd) -> tuple[int, str]:
    try:
        p = subprocess.run(cmd, capture_output=True, timeout=60)
    except FileNotFoundError:
        return 127, "找不到命令：" + cmd[0]
    except subprocess.TimeoutExpired:
        return 124, "命令超时（可能弹了确认框没点）"
    raw = (p.stdout or b"") + (p.stderr or b"")
    for enc in ("mbcs", "utf-8", "gbk"):
        try:
            return p.returncode, raw.decode(enc)
        except Exception:
            continue
    return p.returncode, raw.decode("utf-8", "replace")


def ca_trusted() -> bool:
    if sys.platform != "win32":
        return False
    rc, txt = _run(["certutil", "-store", "-user", "Root", cert_sha1()])
    if rc != 0:
        return False
    return cert_sha1().replace(" ", "") in txt.upper().replace(" ", "")


def cmd_trust(args) -> int:
    if sys.platform != "win32":
        out("这条命令只用于 Windows。手机请按 README 第 1 节装描述文件/证书。")
        return 1
    if not CA_CRT.exists():
        ensure_ca()
    sha1 = cert_sha1()
    if args.remove:
        rc, txt = _run(["certutil", "-delstore", "-user", "Root", sha1])
        ok = rc == 0
        out(("已从「当前用户 → 受信任的根证书颁发机构」移除。" if ok
             else f"移除失败（rc={rc}）：\n{txt.strip()[:600]}"))
        return 0 if ok else 1
    if ca_trusted():
        out("这个 CA 已经在「当前用户 → 受信任的根证书颁发机构」里了，不用重复安装。")
        return 0
    rc, txt = _run(["certutil", "-addstore", "-user", "Root", str(CA_CRT)])
    if rc != 0:
        out(f"安装失败（rc={rc}）：\n{txt.strip()[:600]}")
        return 1
    if not ca_trusted():
        out("certutil 返回成功，但没在证书库里查到，请手动检查 certmgr.msc。")
        return 1
    out("已装进「当前用户 → 受信任的根证书颁发机构」（只影响当前 Windows 账号）。")
    out("浏览器 / Chromium 内核的程序（含 PC 微信小程序容器）会信任它。")
    out("不用了记得：python pcap\\pcap.py trust --remove")
    return 0


def find_wechatappex() -> Path | None:
    bases = []
    appdata = os.environ.get("APPDATA")
    if appdata:
        bases.append(Path(appdata) / "Tencent")
    bases += [Path(r"C:\Program Files\Tencent"), Path(r"C:\Program Files (x86)\Tencent")]
    hits = []
    for base in bases:
        if not base.exists():
            continue
        for pat in ("xwechat/xplugin/plugins/*/WeChatAppEx.exe",
                    "WeChat/*/WeChatAppEx.exe",
                    "*/WeChatAppEx.exe"):
            try:
                hits += list(base.glob(pat))
            except OSError:
                pass
    hits = [h for h in hits if h.exists()]
    if not hits:
        return None
    hits.sort(key=lambda p: ("Radium" not in str(p), len(str(p))))
    return hits[0]


def cmd_pc(args) -> int:
    exe = find_wechatappex()
    trusted = ca_trusted() if sys.platform == "win32" else False
    out("")
    out("PC 微信小程序抓包 —— 本机情况")
    out(f"  证书信任   {'已装（当前用户根证书）' if trusted else '未装 → 先运行  python pcap\\pcap.py trust'}")
    out(f"  小程序进程 {exe if exe else '没找到（打开任意小程序后：任务管理器 → WeChatAppEx.exe → 右键「打开文件所在位置」）'}")
    out("")
    out("步骤：")
    out("  1. python pcap\\pcap.py trust        # 只装一次，装到当前用户根证书")
    out("  2. python pcap\\pcap.py run          # 看端口，默认 8080")
    out("  3. Proxifier → Profile → Proxy Servers 添加 127.0.0.1:8080，协议 HTTPS")
    out("  4. Proxifier → Proxification Rules 新增一条：")
    if exe:
        out(f"       Applications: {exe}")
    else:
        out("       Applications: WeChatAppEx.exe（先按上面方法找到路径）")
    out("       Action: 第 3 步那个代理；这条规则必须排在 Default 之上")
    out("  5. 完全退出微信（右下角托盘右键 → 退出），重开 → 进活动小程序")
    out("  6. 回来看：python pcap\\pcap.py list")
    out("")
    out("说明：微信主程序 Weixin.exe 没流量是正常的，小程序请求由 WeChatAppEx.exe 发出，")
    out("      它不读 Windows 系统代理，所以必须要 Proxifier 这类按进程转发的工具。")
    out("      没用微信时记得 trust --remove，或至少在 Proxifier 里停用规则。")
    return 0


# --------------------------------------------------------------------------
# 入口
# --------------------------------------------------------------------------
def build_parser():
    p = argparse.ArgumentParser(
        prog="pcap.py", description="本机 HTTPS 抓包（微信小程序接口分析）")
    p.add_argument("-V", "--version", action="version", version=f"pcap.py {VERSION}")
    sub = p.add_subparsers(dest="cmd")

    def add_session(sp):
        sp.add_argument("-s", "--session", default="latest", help="会话名，默认 latest")
        sp.add_argument("--out", default=None, help="captures 目录（默认 pcap/captures）")

    r = sub.add_parser("run", help="启动抓包")
    r.add_argument("--bind", default="0.0.0.0", help="监听地址，默认 0.0.0.0；只想本机用 127.0.0.1")
    r.add_argument("--port", type=int, default=8080)
    r.add_argument("--out", default=None, help="输出目录")
    r.add_argument("--only", default="", help="只抓这些域名，逗号分隔，支持 * ；例 *.fjtcm.edu.cn")
    r.add_argument("--exclude", default="", help="额外排除的域名")
    r.add_argument("--keep-wechat", action="store_true", help="不过滤微信/系统噪音域名")
    r.add_argument("--save-images", action="store_true", help="连图片响应体一起存（默认只存头）")
    r.add_argument("--max-body", default=str(MAX_BODY_DEFAULT), help="单条响应体上限，默认 2MB")
    r.add_argument("--timeout", type=float, default=30.0)
    r.add_argument("--insecure-upstream", action="store_true",
                   help="不校验上游证书（自签测试用）")
    r.add_argument("--upstream-proxy", default="auto",
                   help="上游代理：auto=读 Windows 系统代理（默认），off=直连，或 http://127.0.0.1:7890")
    r.set_defaults(func=cmd_run)

    l = sub.add_parser("list", help="列出抓到的请求")
    add_session(l)
    l.set_defaults(func=cmd_list)

    s = sub.add_parser("show", help="看某条请求详情")
    s.add_argument("id")
    s.add_argument("--full", action="store_true", help="不截断")
    s.add_argument("--raw", action="store_true", help="附原始 base64")
    add_session(s)
    s.set_defaults(func=cmd_show)

    h = sub.add_parser("har", help="导出 HAR")
    h.add_argument("-o", "--output", default=None)
    h.add_argument("--no-redact", action="store_true", help="不要打码（危险）")
    add_session(h)
    h.set_defaults(func=cmd_har)

    rp = sub.add_parser("replay", help="原样重放某条请求")
    rp.add_argument("id")
    rp.add_argument("--send", action="store_true", help="非 GET 请求必须加这个才会真的发")
    rp.add_argument("--repeat", type=int, default=1)
    rp.add_argument("--timeout", type=float, default=20.0)
    rp.add_argument("--insecure", action="store_true")
    rp.add_argument("--upstream-proxy", default="off")
    rp.add_argument("--show-body", action="store_true")
    add_session(rp)
    rp.set_defaults(func=cmd_replay)

    c = sub.add_parser("ca", help="查看/重新生成 CA")
    c.add_argument("--regen", action="store_true", help="重新生成（旧证书立即失效）")
    c.set_defaults(func=cmd_ca)

    t = sub.add_parser("trust", help="把 CA 装进 Windows 当前用户根证书（PC 微信/浏览器用）")
    t.add_argument("--remove", action="store_true", help="卸载")
    t.set_defaults(func=cmd_trust)

    pc = sub.add_parser("pc", help="PC 微信抓包步骤（自动检测 WeChatAppEx.exe）")
    pc.set_defaults(func=cmd_pc)
    return p


def main(argv=None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv:
        argv = ["run"]
    p = build_parser()
    args = p.parse_args(argv)
    if not getattr(args, "func", None):
        p.print_help()
        return 2
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
