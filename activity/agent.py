#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
activity/agent.py —— 第二课堂（rcm.fjtcm.edu.cn / stmapi.fjtcm.edu.cn）本地助手

在 127.0.0.1 上跑一个小服务，给班级工具站的「活动」页用；也可以直接当命令行用。

它做三件事：
  1. 用抓包得到的 token + 逆向出的签名算法，直接调学校接口（不经过微信）
  2. 列出可报名活动、看名额、报名/取消（默认 dry-run）
  3. 把结果以 JSON 暴露给本机网页

签名算法（2026-11-14 实测通过，30/30 抓包样本吻合）：
    Authorization = base64( ts + ":" + nonce + ":" + md5(salt + 完整URL(不含query) + ts + nonce) + ":" + token )
    salt = "rndAgtFzYJpyKlRY"，ts 为秒级时间戳，nonce 为 16 位随机字母数字

用法：
    python activity\\agent.py import-token          # 从最新的 pcap 抓包里取 token
    python activity\\agent.py list                  # 活动列表
    python activity\\agent.py show <活动id>          # 详情 + 各角色名额
    python activity\\agent.py sign <活动id>          # 只打印将要发的请求（dry-run）
    python activity\\agent.py sign <活动id> --apply  # 真的报名
    python activity\\agent.py cancel <活动id> --apply
    python activity\\agent.py serve                 # 给网页用，127.0.0.1:8790
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import http.client
import json
import os
import random
import re
import socket
import ssl
import string
import sys
import threading
import time
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit, parse_qs

ROOT = Path(__file__).resolve().parent
TOKEN_PATH = ROOT / "token.json"
CONFIG_PATH = ROOT / "config.json"
PCAP_CAPTURES = ROOT.parent / "pcap" / "captures"

BASE = "https://stmapi.fjtcm.edu.cn"
SALT = "rndAgtFzYJpyKlRY"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/144.0.0.0 Safari/537.36")
ALLOW_ORIGINS = {
    "http://121.196.47.2", "https://121.196.47.2",
    "http://127.0.0.1:8787", "http://localhost:8787",
    "http://127.0.0.1:8000", "http://localhost:8000",
}

_ctx = ssl.create_default_context()
try:
    _ctx.set_ciphers("DEFAULT@SECLEVEL=0")   # 学校服务器 DH 只有 1024 位
except ssl.SSLError:
    pass


# --------------------------------------------------------------------------
# 签名 + 请求
# --------------------------------------------------------------------------
def sign(url: str, token: str) -> str:
    """url 必须是完整 URL 且不含 query。"""
    ts = str(int(time.time()))
    nonce = "".join(random.choice(string.ascii_letters + string.digits) for _ in range(16))
    digest = hashlib.md5((SALT + url + ts + nonce).encode()).hexdigest()
    return base64.b64encode(f"{ts}:{nonce}:{digest}:{token}".encode()).decode()


def api(method: str, path: str, query: str = "", body=None, token: str = "", timeout=20):
    url = BASE + path
    full = url + (("?" + query) if query else "")
    data = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
    headers = {
        "Authorization": sign(url, token),
        "Accept": "application/json, text/plain, */*",
        "Origin": "https://rcm.fjtcm.edu.cn",
        "Referer": "https://rcm.fjtcm.edu.cn/",
        "User-Agent": UA,
    }
    if data is not None:
        headers["Content-Type"] = "application/json;charset=UTF-8"
    conn = http.client.HTTPSConnection("stmapi.fjtcm.edu.cn", 443, timeout=timeout, context=_ctx)
    try:
        conn.request(method, path + (("?" + query) if query else ""), body=data, headers=headers)
        resp = conn.getresponse()
        raw = resp.read()
        return resp.status, raw
    finally:
        conn.close()


def api_json(method: str, path: str, query: str = "", body=None, token: str = ""):
    status, raw = api(method, path, query, body, token)
    if status != 200:
        raise SystemExit(f"接口返回 {status}（{path}）")
    return json.loads(raw.decode("utf-8"))


# --------------------------------------------------------------------------
# 本地状态
# --------------------------------------------------------------------------
def load_state() -> dict:
    if TOKEN_PATH.exists():
        try:
            return json.loads(TOKEN_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def save_state(state: dict) -> None:
    TOKEN_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")
    try:
        os.chmod(TOKEN_PATH, 0o600)
    except Exception:
        pass


def load_config() -> dict:
    cfg = {"salt": SALT, "port": 8790}
    if CONFIG_PATH.exists():
        try:
            cfg.update(json.loads(CONFIG_PATH.read_text(encoding="utf-8")))
        except Exception:
            pass
    return cfg


def out(msg: str = "") -> None:
    try:
        print(msg, flush=True)
    except UnicodeEncodeError:
        print(msg.encode("utf-8", "replace").decode("utf-8", "replace"), flush=True)


def ts_str(ms) -> str:
    if not ms:
        return "-"
    return datetime.fromtimestamp(ms / 1000).strftime("%m-%d %H:%M")


# --------------------------------------------------------------------------
# 从抓包导入 token
# --------------------------------------------------------------------------
def cmd_import_token(args) -> int:
    if not PCAP_CAPTURES.exists():
        out(f"找不到抓包目录：{PCAP_CAPTURES}")
        out("先用 pcap 抓一次（打开小程序即可）。")
        return 1
    sessions = sorted([p for p in PCAP_CAPTURES.iterdir() if p.is_dir()],
                      key=lambda p: p.stat().st_mtime, reverse=True)
    token = token_from = None
    uid = cid = None
    for sess in sessions:
        for f in sorted(sess.glob("*.json"), reverse=True):
            if f.name == "meta.json":
                continue
            try:
                rec = json.loads(f.read_text(encoding="utf-8"))
            except Exception:
                continue
            url = rec.get("url") or ""
            if uid is None:
                m = re.search(r"/for_sign/([0-9a-f]{32})/class/([0-9a-f]{32})", url)
                if m:
                    uid, cid = m.group(1), m.group(2)
            if token is None and "stmapi" in url:
                auth = next((v for k, v in rec.get("req_headers") or [] if k.lower() == "authorization"), "")
                if auth:
                    try:
                        parts = base64.b64decode(auth + "=" * (-len(auth) % 4)).decode().split(":")
                    except Exception:
                        parts = []
                    if len(parts) == 4 and len(parts[3]) >= 16:
                        token, token_from = parts[3], f"{sess.name}/{f.stem}"
        if token and uid:
            break
    if not token:
        out("抓包里没找到有效 token：先开 pcap + 打开小程序，让页面登录一次。")
        return 1
    if not uid:
        out("抓包里没找到 userId/classId：在小程序里进一次活动列表页再抓。")
        return 1
    state = {"token": token, "userId": uid, "classId": cid,
             "savedAt": datetime.now().astimezone().isoformat(timespec="seconds"),
             "from": token_from}
    save_state(state)
    out(f"已保存 token（来自 {token_from}）")
    out(f"  userId   {uid}")
    out(f"  classId  {cid}")
    return 0


# --------------------------------------------------------------------------
# 业务
# --------------------------------------------------------------------------
def require_state() -> dict:
    st = load_state()
    if not st.get("token"):
        raise SystemExit("还没有 token：先运行  python activity\\agent.py import-token")
    return st


def fetch_list(st: dict, page=1, rows=20, order=0) -> dict:
    path = f"/organizations/activity/page/for_sign/{st['userId']}/class/{st['classId']}"
    return api_json("POST", path, f"orderBy={order}&page={page}&rows={rows}", {"type": ""}, st["token"])


def fetch_detail(st: dict, activity_id: str) -> dict:
    path = f"/organizations/activity/all/{activity_id}"
    return api_json("GET", path, f"studentUserId={st['userId']}", None, st["token"])


def pick_role(detail: dict, want: str = "") -> dict | None:
    roles = detail.get("activityRoleConfigs") or []
    if want:
        for r in roles:
            role = r.get("signUpRole") or {}
            if want in (role.get("name") or ""):
                return r
        return None
    for r in roles:
        role = r.get("signUpRole") or {}
        if "参与者" in (role.get("name") or ""):
            return r
    for r in roles:
        if r.get("numLimit") is not None:
            return r
    return roles[0] if roles else None


def quota_text(role: dict) -> str:
    limit = role.get("numLimit")
    used = role.get("signUpNum")
    if limit is None:
        return f"不限（已报 {used}）"
    left = max(0, int(limit) - int(used or 0))
    return f"{used}/{limit}（剩 {left}）"


def cmd_list(args) -> int:
    st = require_state()
    data = fetch_list(st, args.page, args.rows)
    items = data.get("list") or []
    out(f"共 {data.get('total')} 条，第 {data.get('pageNum')} 页 / {len(items)} 条")
    out("")
    out(f"{'ID':<34}{'状态':<6}{'活动时间':<14}{'名称'}")
    for a in items:
        out(f"{a.get('id',''):<34}{a.get('state',''):<6}{ts_str(a.get('actBeginTime')):<14}{a.get('name','')}")
    return 0


def cmd_show(args) -> int:
    st = require_state()
    d = fetch_detail(st, args.id)
    out("")
    out(f"{d.get('name')}")
    out(f"  id        {d.get('id')}")
    out(f"  状态      state={d.get('state')} progressState={d.get('progressState')} isSignUp={d.get('isSignUp')}")
    out(f"  活动时间  {ts_str(d.get('actBeginTime'))} ~ {ts_str(d.get('actEndTime'))}")
    out(f"  报名时间  {ts_str(d.get('supBeginTime'))} ~ {ts_str(d.get('supEndTime'))}")
    out("  角色名额：")
    for r in d.get("activityRoleConfigs") or []:
        role = r.get("signUpRole") or {}
        out(f"    {role.get('name','?'):<8} supRoleId={r.get('supRoleId')}  {quota_text(r)}")
    return 0


def cmd_sign(args) -> int:
    st = require_state()
    d = fetch_detail(st, args.id)
    role = pick_role(d, args.role)
    if not role:
        out(f"找不到角色：{args.role or '参与者'}")
        return 2
    name = (role.get("signUpRole") or {}).get("name", "?")
    out(f"活动    {d.get('name')}")
    out(f"角色    {name}  {quota_text(role)}")
    limit, used = role.get("numLimit"), role.get("signUpNum") or 0
    if limit is not None and used >= int(limit):
        out("名额已满，提交也只会被服务器拒绝。")
    path = f"/organizations/sign_up/activity/{args.id}/role/{role.get('supRoleId')}/user/{st['userId']}"
    out(f"请求    POST {BASE}{path}")
    if not args.apply:
        out("")
        out("dry-run：确认无误后加 --apply 才会真的提交。")
        return 0
    status, raw = api("POST", path, "", None, st["token"])
    out(f"结果    {status} {raw[:200].decode('utf-8', 'replace')}")
    return 0 if status == 200 else 1


def cmd_cancel(args) -> int:
    st = require_state()
    path = f"/organizations/sign_up/cancel/{args.id}/user/{st['userId']}"
    if not args.apply:
        out(f"请求    POST {BASE}{path}")
        out("dry-run：确认后加 --apply。")
        return 0
    status, raw = api("POST", path, "", None, st["token"])
    out(f"结果    {status} {raw[:200].decode('utf-8', 'replace')}")
    return 0 if status == 200 else 1


# --------------------------------------------------------------------------
# 给网页用的本地服务
# --------------------------------------------------------------------------
class Handler(BaseHTTPRequestHandler):
    server_version = "activity-agent/1.0"

    def log_message(self, *a):
        pass

    def _cors(self):
        origin = self.headers.get("Origin", "")
        if origin in ALLOW_ORIGINS or origin.startswith("http://127.0.0.1:") or origin.startswith("http://localhost:"):
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.send_header("Access-Control-Allow-Methods", "GET,POST,OPTIONS")

    def _json(self, obj, status=200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self._cors()
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.end_headers()

    def do_GET(self):
        u = urlsplit(self.path)
        q = parse_qs(u.query)
        st = load_state()
        try:
            if u.path == "/health":
                return self._json({"ok": True, "hasToken": bool(st.get("token")),
                                   "userId": st.get("userId"), "savedAt": st.get("savedAt")})
            if u.path == "/list":
                if not st.get("token"):
                    return self._json({"ok": False, "error": "no token"}, 400)
                data = fetch_list(st, int(q.get("page", ["1"])[0]), int(q.get("rows", ["20"])[0]))
                items = [{"id": a.get("id"), "name": a.get("name"), "state": a.get("state"),
                          "actBeginTime": a.get("actBeginTime"), "actEndTime": a.get("actEndTime"),
                          "supBeginTime": a.get("supBeginTime"), "supEndTime": a.get("supEndTime")}
                         for a in (data.get("list") or [])]
                return self._json({"ok": True, "total": data.get("total"), "items": items})
            if u.path.startswith("/detail/"):
                aid = u.path.split("/")[-1]
                d = fetch_detail(st, aid)
                roles = [{"supRoleId": r.get("supRoleId"), "name": (r.get("signUpRole") or {}).get("name"),
                          "numLimit": r.get("numLimit"), "signUpNum": r.get("signUpNum")}
                         for r in (d.get("activityRoleConfigs") or [])]
                return self._json({"ok": True, "id": d.get("id"), "name": d.get("name"),
                                   "state": d.get("state"), "isSignUp": d.get("isSignUp"),
                                   "roles": roles})
            return self._json({"ok": False, "error": "not found"}, 404)
        except SystemExit as e:
            return self._json({"ok": False, "error": str(e)}, 400)
        except Exception as e:
            return self._json({"ok": False, "error": f"{type(e).__name__}: {e}"}, 500)

    def do_POST(self):
        u = urlsplit(self.path)
        length = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(length) or b"{}") if length else {}
        st = load_state()
        try:
            if u.path.startswith("/sign/"):
                aid = u.path.split("/")[-1]
                d = fetch_detail(st, aid)
                role = pick_role(d, "")
                path = f"/organizations/sign_up/activity/{aid}/role/{role.get('supRoleId')}/user/{st['userId']}"
                if not body.get("apply"):
                    return self._json({"ok": True, "dryRun": True, "path": path})
                status, raw = api("POST", path, "", None, st["token"])
                return self._json({"ok": status == 200, "status": status,
                                   "body": raw[:300].decode("utf-8", "replace")})
            if u.path.startswith("/cancel/"):
                aid = u.path.split("/")[-1]
                path = f"/organizations/sign_up/cancel/{aid}/user/{st['userId']}"
                if not body.get("apply"):
                    return self._json({"ok": True, "dryRun": True, "path": path})
                status, raw = api("POST", path, "", None, st["token"])
                return self._json({"ok": status == 200, "status": status,
                                   "body": raw[:300].decode("utf-8", "replace")})
            return self._json({"ok": False, "error": "not found"}, 404)
        except SystemExit as e:
            return self._json({"ok": False, "error": str(e)}, 400)
        except Exception as e:
            return self._json({"ok": False, "error": f"{type(e).__name__}: {e}"}, 500)


def cmd_serve(args) -> int:
    cfg = load_config()
    port = args.port or cfg.get("port", 8790)
    srv = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    st = load_state()
    out(f"activity agent 已启动 http://127.0.0.1:{port}")
    out(f"  token    {'已就绪（' + str(st.get('savedAt')) + '）' if st.get('token') else '未导入'}")
    out(f"  给网页用的接口：/health /list /detail/<id> /sign/<id> /cancel/<id>")
    out("")
    out("网页端：工具站「活动」页会把请求发到这里；只监听 127.0.0.1。")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        out("已停止")
    return 0


# --------------------------------------------------------------------------
def main(argv=None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    p = argparse.ArgumentParser(prog="activity-agent", description="第二课堂本地助手")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("import-token", help="从最新 pcap 抓包导入 token")
    s.set_defaults(func=cmd_import_token)

    s = sub.add_parser("list", help="活动列表")
    s.add_argument("--page", type=int, default=1)
    s.add_argument("--rows", type=int, default=20)
    s.set_defaults(func=cmd_list)

    s = sub.add_parser("show", help="活动详情")
    s.add_argument("id")
    s.set_defaults(func=cmd_show)

    s = sub.add_parser("sign", help="报名（默认 dry-run）")
    s.add_argument("id")
    s.add_argument("--role", default="", help="角色名，默认参与者")
    s.add_argument("--apply", action="store_true")
    s.set_defaults(func=cmd_sign)

    s = sub.add_parser("cancel", help="取消报名（默认 dry-run）")
    s.add_argument("id")
    s.add_argument("--apply", action="store_true")
    s.set_defaults(func=cmd_cancel)

    s = sub.add_parser("serve", help="给网页用的本地服务")
    s.add_argument("--port", type=int, default=0)
    s.set_defaults(func=cmd_serve)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
