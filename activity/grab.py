#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
grab.py —— 第二课堂「抢活动」独立电脑脚本（单文件 · 图形界面）

不需要工具站、不需要服务器：登录、看名额、监控、报名全在这一个脚本里。
只依赖 Python 3.8+；登录用 Edge/Chrome 的调试端口，需要 websocket-client：
    python -m pip install websocket-client

用法：
    双击「抢活动.cmd」，或  python grab.py
    python grab.py --selftest      # 校验签名/配置，不开界面
    python grab.py --smoke         # 界面自检：开 1 秒就关

数据：
    grab.json（同目录，含学校 token，别外传/别提交）
"""
from __future__ import annotations

import base64
import hashlib
import http.client
import json
import os
import random
import re
import ssl
import string
import subprocess
import sys
import threading
import time
import urllib.request
from datetime import datetime
from pathlib import Path

try:
    import tkinter as tk
    from tkinter import messagebox, ttk
except Exception:  # 无 Tk 时只保留命令行
    tk = None

ROOT = Path(__file__).resolve().parent
STATE_PATH = ROOT / "grab.json"
BASE = "https://stmapi.fjtcm.edu.cn"
SALT = "rndAgtFzYJpyKlRY"
SPA_URL = "https://rcm.fjtcm.edu.cn/wechat/"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/144.0.0.0 Safari/537.36")

# 单测/自检用的真实抓包样本（2026-11-14，30/30 吻合）
VECTOR_URL = "https://stmapi.fjtcm.edu.cn/basic/school/no"
VECTOR_TS = "1794668287"
VECTOR_NONCE = "I5Bn9M50lZq4AYAK"
VECTOR_HEADER = ("MTc5NDY2ODI4NzpJNUJuOU01MGxacTRBWUFLOmFhYTg2ZmE3YWU0MDc3"
                 "NWZmNjFjYTU5N2JmYzQzMTlhOg==")

_ctx = ssl.create_default_context()
try:
    _ctx.set_ciphers("DEFAULT@SECLEVEL=0")   # 学校服务器 DH 只有 1024 位
except ssl.SSLError:
    pass


# --------------------------------------------------------------------------
# 签名 / 配置
# --------------------------------------------------------------------------
def sign(url: str, token: str, ts: str, nonce: str) -> str:
    """base64(ts:nonce:md5(salt+完整URL(不含query)+ts+nonce):token)"""
    digest = hashlib.md5((SALT + url + ts + nonce).encode("utf-8")).hexdigest()
    return base64.b64encode(f"{ts}:{nonce}:{digest}:{token}".encode()).decode()


def auth_header(url: str, token: str) -> str:
    ts = str(int(time.time()))
    nonce = "".join(random.choice(string.ascii_letters + string.digits) for _ in range(16))
    return sign(url, token, ts, nonce)


def load_state() -> dict:
    if STATE_PATH.exists():
        try:
            return json.loads(STATE_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    # 兼容旧版 agent.py 留下的 token.json（同目录）
    legacy = ROOT / "token.json"
    if legacy.exists():
        try:
            old = json.loads(legacy.read_text(encoding="utf-8"))
            if old.get("token"):
                return old
        except Exception:
            pass
    return {}


def save_state(state: dict) -> None:
    STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")
    try:
        os.chmod(STATE_PATH, 0o600)
    except Exception:
        pass


# --------------------------------------------------------------------------
# 学校接口
# --------------------------------------------------------------------------
class ApiError(RuntimeError):
    def __init__(self, status: int, body: str = ""):
        self.status = status
        super().__init__(f"接口返回 {status}" + (f"：{body[:120]}" if body else ""))


def api(method: str, path: str, query: str = "", body=None, token: str = "", timeout=15):
    url = BASE + path
    data = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
    headers = {
        "Authorization": auth_header(url, token),
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


def fetch_list(st: dict, rows=50) -> list:
    path = f"/organizations/activity/page/for_sign/{st['userId']}/class/{st['classId']}"
    status, raw = api("POST", path, f"orderBy=0&page=1&rows={rows}", {"type": ""}, st.get("token", ""))
    if status != 200:
        raise ApiError(status, raw[:120].decode("utf-8", "replace"))
    root = json.loads(raw.decode("utf-8"))
    return root.get("list") or []


def fetch_detail(st: dict, activity_id: str) -> dict:
    path = f"/organizations/activity/all/{activity_id}"
    status, raw = api("GET", path, f"studentUserId={st['userId']}", None, st.get("token", ""))
    if status != 200:
        raise ApiError(status, raw[:120].decode("utf-8", "replace"))
    return json.loads(raw.decode("utf-8"))


def roles_of(detail: dict) -> list:
    out = []
    for rc in detail.get("activityRoleConfigs") or []:
        role = rc.get("signUpRole") or {}
        out.append({
            "roleId": rc.get("supRoleId") or "",
            "name": role.get("name") or "角色",
            "limit": rc.get("numLimit"),
            "used": int(rc.get("signUpNum") or 0),
        })
    return out


def pick_role(roles: list, prefer: str = "") -> dict | None:
    if prefer:
        for r in roles:
            if prefer in r["name"]:
                return r
    for r in roles:
        if "参与者" in r["name"]:
            return r
    for r in roles:
        if r["limit"] is not None:
            return r
    return roles[0] if roles else None


def sign_up(st: dict, activity_id: str, role_id: str):
    path = f"/organizations/sign_up/activity/{activity_id}/role/{role_id}/user/{st['userId']}"
    return api("POST", path, "", None, st.get("token", ""))


def cancel_sign(st: dict, activity_id: str):
    path = f"/organizations/sign_up/cancel/{activity_id}/user/{st['userId']}"
    return api("POST", path, "", None, st.get("token", ""))


# --------------------------------------------------------------------------
# 浏览器辅助登录（不接触密码）
# --------------------------------------------------------------------------
def find_browser() -> str:
    for p in (
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    ):
        if os.path.exists(p):
            return p
    return "msedge"


def _http_json(url: str, timeout=3.0):
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def parse_lg_info(raw: str) -> dict | None:
    """CDP evaluateJavascript 返回的是 JSON 字符串，lgInfo 本身又是 JSON 文本。"""
    if not raw:
        return None
    try:
        if raw.startswith('"') and raw.endswith('"'):
            raw = json.loads(raw)
    except Exception:
        pass
    if not isinstance(raw, str) or not raw.strip().startswith("{"):
        return None
    try:
        obj = json.loads(raw)
    except Exception:
        return None
    token, uid, cid = obj.get("token"), obj.get("userId"), obj.get("classId")
    if not token or not uid or not cid:
        return None
    return {"token": token, "userId": uid, "classId": cid}


def browser_login(port=9224, timeout=240, log=print) -> dict | None:
    try:
        import websocket  # websocket-client
    except ImportError:
        log("缺少依赖：python -m pip install websocket-client")
        return None
    profile = ROOT / "browser-profile"
    profile.mkdir(exist_ok=True)
    log("正在打开浏览器，请用「统一身份认证」登录（学号+密码）…")
    try:
        subprocess.Popen(
            [find_browser(), f"--remote-debugging-port={port}",
             f"--user-data-dir={profile}", "--no-first-run",
             "--no-default-browser-check", SPA_URL],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
    except FileNotFoundError:
        log("找不到 Edge/Chrome")
        return None

    ws_url = None
    for _ in range(40):
        try:
            for t in _http_json(f"http://127.0.0.1:{port}/json/list"):
                if t.get("type") == "page" and "rcm.fjtcm" in (t.get("url") or ""):
                    ws_url = t.get("webSocketDebuggerUrl")
                    break
        except Exception:
            pass
        if ws_url:
            break
        time.sleep(0.5)
    if not ws_url:
        log("连不上浏览器调试端口（可能被安全软件拦了）")
        return None

    ws = websocket.create_connection(ws_url, timeout=10)
    expr = "(()=>{try{return localStorage.getItem('lgInfo')||''}catch(e){return ''}})()"
    deadline = time.time() + timeout
    found = None
    try:
        while time.time() < deadline:
            try:
                ws.send(json.dumps({"id": 1, "method": "Runtime.evaluate",
                                    "params": {"expression": expr, "returnByValue": True}}))
                msg = json.loads(ws.recv())
                val = ((msg.get("result") or {}).get("result") or {}).get("value") or ""
            except Exception:
                val = ""
            info = parse_lg_info(val)
            if info:
                found = info
                break
            time.sleep(1.2)
    finally:
        try:
            ws.close()
        except Exception:
            pass
    return found


# --------------------------------------------------------------------------
# 图形界面
# --------------------------------------------------------------------------
def fmt(ms) -> str:
    if not ms:
        return "—"
    try:
        return datetime.fromtimestamp(ms / 1000).strftime("%m-%d %H:%M")
    except Exception:
        return "—"


def beep() -> None:
    try:
        import winsound
        winsound.Beep(880, 250)
    except Exception:
        pass


class App:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.state = load_state()
        self.activities: list = []
        self.detail: dict | None = None
        self.roles: list = []
        self.watch_stop = threading.Event()
        self.watch_thread: threading.Thread | None = None
        self.busy = False

        root.title("抢活动 · 第二课堂")
        root.geometry("980x680")
        root.minsize(820, 560)
        self._build()
        self._refresh_login_state()
        if self.state.get("token"):
            self.root.after(300, self.reload_list)

    # ---------------------------------------------------------------- UI
    def _build(self):
        top = ttk.Frame(self.root, padding=(10, 8))
        top.pack(fill="x")
        self.login_label = ttk.Label(top, text="未登录")
        self.login_label.pack(side="left")
        ttk.Button(top, text="登录学校账号", command=self.do_login).pack(side="left", padx=8)
        ttk.Button(top, text="刷新列表", command=self.reload_list).pack(side="left")
        ttk.Button(top, text="清除登录", command=self.clear_login).pack(side="left", padx=8)

        body = ttk.PanedWindow(self.root, orient="horizontal")
        body.pack(fill="both", expand=True, padx=10, pady=(0, 6))

        left = ttk.Frame(body)
        body.add(left, weight=3)
        cols = ("sup", "act")
        self.tree = ttk.Treeview(left, columns=cols, show="tree headings", height=18)
        self.tree.heading("#0", text="活动")
        self.tree.heading("sup", text="报名时间")
        self.tree.heading("act", text="活动时间")
        self.tree.column("#0", width=300, stretch=True)
        self.tree.column("sup", width=110, stretch=False)
        self.tree.column("act", width=110, stretch=False)
        self.tree.pack(fill="both", expand=True)
        self.tree.bind("<<TreeviewSelect>>", lambda e: self.on_select())

        right = ttk.Frame(body, padding=(8, 0))
        body.add(right, weight=2)
        ttk.Label(right, text="名额 / 报名").pack(anchor="w")
        self.detail_text = tk.Text(right, height=12, wrap="word", state="disabled")
        self.detail_text.pack(fill="both", expand=True, pady=4)

        row = ttk.Frame(right)
        row.pack(fill="x", pady=2)
        ttk.Label(row, text="角色").pack(side="left")
        self.role_box = ttk.Combobox(row, state="readonly", width=14)
        self.role_box.pack(side="left", padx=6)
        ttk.Button(row, text="报名", command=self.do_sign).pack(side="left")
        ttk.Button(row, text="取消报名", command=self.do_cancel).pack(side="left", padx=6)

        ctrl = ttk.LabelFrame(right, text="监控（有名额时自动抢）", padding=8)
        ctrl.pack(fill="x", pady=(6, 0))
        line1 = ttk.Frame(ctrl)
        line1.pack(fill="x")
        self.auto_var = tk.BooleanVar(value=bool(self.state.get("settings", {}).get("autoSign")))
        ttk.Checkbutton(line1, text="自动报名", variable=self.auto_var).pack(side="left")
        ttk.Label(line1, text="间隔(秒)").pack(side="left", padx=(12, 4))
        self.interval_var = tk.StringVar(value=str(self.state.get("settings", {}).get("interval", 3)))
        ttk.Spinbox(line1, from_=1, to=60, width=5, textvariable=self.interval_var).pack(side="left")
        line2 = ttk.Frame(ctrl)
        line2.pack(fill="x", pady=(6, 0))
        self.watch_btn = ttk.Button(line2, text="开始监控", command=self.toggle_watch)
        self.watch_btn.pack(side="left")
        self.watch_label = ttk.Label(line2, text="空闲")
        self.watch_label.pack(side="left", padx=8)

        logf = ttk.LabelFrame(self.root, text="日志", padding=(8, 4))
        logf.pack(fill="both", expand=True, padx=10, pady=(0, 8))
        self.log_text = tk.Text(logf, height=7, wrap="word", state="disabled")
        self.log_text.pack(fill="both", expand=True)
        self.log("准备就绪。首次使用请点「登录学校账号」。")

    # ---------------------------------------------------------------- 工具
    def log(self, msg: str):
        line = f"[{datetime.now().strftime('%H:%M:%S')}] {msg}\n"

        def put():
            self.log_text.configure(state="normal")
            self.log_text.insert("end", line)
            self.log_text.see("end")
            self.log_text.configure(state="disabled")

        try:
            self.root.after(0, put)
        except Exception:
            print(line, end="")

    def _refresh_login_state(self):
        st = self.state
        if st.get("token"):
            when = st.get("savedAt", "")
            self.login_label.configure(text=f"已登录（{when}）")
        else:
            self.login_label.configure(text="未登录")

    def _set_busy(self, busy: bool):
        self.busy = busy

    def _selected_id(self):
        sel = self.tree.selection()
        return sel[0] if sel else ""

    # ---------------------------------------------------------------- 动作
    def do_login(self):
        def work():
            info = browser_login(log=self.log)
            if not info:
                self.log("登录未完成：浏览器里登录成功后，回到窗口点「刷新列表」；也可重试。")
                return
            info["savedAt"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            info.setdefault("settings", self.state.get("settings", {}))
            self.state.update(info)
            save_state(self.state)
            self.root.after(0, self._refresh_login_state)
            self.log("登录成功，token 已保存到本机。")
            self.root.after(0, self.reload_list)

        threading.Thread(target=work, daemon=True).start()

    def clear_login(self):
        self.state.pop("token", None)
        self.state.pop("userId", None)
        self.state.pop("classId", None)
        save_state(self.state)
        self._refresh_login_state()
        self.tree.delete(*self.tree.get_children())
        self._set_detail_text("")
        self.log("已清除本机登录。")

    def reload_list(self):
        if not self.state.get("token"):
            self.log("还没登录：先点「登录学校账号」。")
            return

        def work():
            try:
                items = fetch_list(self.state)
            except ApiError as e:
                self.log(f"列表加载失败：{e}（401 就是登录过期，重新登录）")
                return
            except Exception as e:
                self.log(f"列表加载失败：{type(e).__name__}: {e}")
                return
            self.activities = items
            self.root.after(0, lambda: self._fill_tree(items))
            self.log(f"列表已刷新，共 {len(items)} 条。")

        threading.Thread(target=work, daemon=True).start()

    def _fill_tree(self, items):
        self.tree.delete(*self.tree.get_children())
        for a in items:
            self.tree.insert(
                "", "end", iid=a.get("id") or a.get("name", ""),
                text=a.get("name", ""),
                values=(fmt(a.get("supBeginTime")), fmt(a.get("actBeginTime"))),
            )

    def on_select(self):
        aid = self._selected_id()
        if not aid:
            return

        def work():
            try:
                d = fetch_detail(self.state, aid)
            except ApiError as e:
                self.log(f"详情失败：{e}")
                return
            except Exception as e:
                self.log(f"详情失败：{type(e).__name__}: {e}")
                return
            roles = roles_of(d)
            self.detail = d
            self.roles = roles
            self.root.after(0, lambda: self._render_detail(d, roles))

        threading.Thread(target=work, daemon=True).start()

    def _render_detail(self, d, roles):
        lines = [
            d.get("name", ""),
            f"报名时间：{fmt(d.get('supBeginTime'))} ~ {fmt(d.get('supEndTime'))}",
            f"活动时间：{fmt(d.get('actBeginTime'))} ~ {fmt(d.get('actEndTime'))}",
            f"state={d.get('state')}  isSignUp={d.get('isSignUp')}",
            "",
            "角色名额：",
        ]
        for r in roles:
            if r["limit"] is None:
                lines.append(f"  {r['name']}  已报 {r['used']}（不限）")
            else:
                left = max(0, r["limit"] - r["used"])
                lines.append(f"  {r['name']}  {r['used']}/{r['limit']}，剩 {left}")
        self._set_detail_text("\n".join(lines))
        names = [r["name"] for r in roles]
        self.role_box["values"] = names
        if names:
            pick = self.state.get("settings", {}).get("roleName", "")
            self.role_box.current(names.index(pick) if pick in names else 0)

    def _set_detail_text(self, text: str):
        self.detail_text.configure(state="normal")
        self.detail_text.delete("1.0", "end")
        self.detail_text.insert("1.0", text)
        self.detail_text.configure(state="disabled")

    def _current_role(self):
        idx = self.role_box.current()
        if 0 <= idx < len(self.roles):
            return self.roles[idx]
        return pick_role(self.roles)

    def do_sign(self):
        aid, role = self._selected_id(), self._current_role()
        if not aid or not role:
            self.log("先在左边选一个活动。")
            return
        if role["limit"] is not None and role["used"] >= role["limit"]:
            self.log("这个角色已经满了，提交也会被拒绝。")
            return
        if not messagebox.askyesno("确认报名", f"{self.tree.item(aid, 'text')}\n角色：{role['name']}\n\n确定提交？"):
            return

        def work():
            try:
                status, raw = sign_up(self.state, aid, role["roleId"])
            except Exception as e:
                self.log(f"报名失败：{type(e).__name__}: {e}")
                return
            if status == 200:
                self.log("报名成功。")
                beep()
            else:
                self.log(f"报名被拒：{status} {raw[:160].decode('utf-8', 'replace')}")
            self.root.after(0, self.on_select)

        threading.Thread(target=work, daemon=True).start()

    def do_cancel(self):
        aid = self._selected_id()
        if not aid:
            return
        if not messagebox.askyesno("确认取消", "确定取消这个活动的报名？"):
            return

        def work():
            try:
                status, raw = cancel_sign(self.state, aid)
            except Exception as e:
                self.log(f"取消失败：{type(e).__name__}: {e}")
                return
            self.log("已取消。" if status == 200 else f"取消失败：{status} {raw[:120]}")
            self.root.after(0, self.on_select)

        threading.Thread(target=work, daemon=True).start()

    # ---------------------------------------------------------------- 监控
    def toggle_watch(self):
        if self.watch_thread and self.watch_thread.is_alive():
            self.watch_stop.set()
            self.watch_btn.configure(text="开始监控")
            self.watch_label.configure(text="已停止")
            self.log("监控已停止。")
            return
        aid, role = self._selected_id(), self._current_role()
        if not aid or not role:
            self.log("先在左边选一个活动，再开始监控。")
            return
        try:
            interval = max(1.0, float(self.interval_var.get()))
        except ValueError:
            interval = 3.0
        self.state.setdefault("settings", {})
        self.state["settings"].update({
            "interval": interval, "autoSign": bool(self.auto_var.get()),
            "roleName": role["name"], "activityId": aid,
        })
        save_state(self.state)

        self.watch_stop = threading.Event()
        self.watch_btn.configure(text="停止监控")
        self.watch_label.configure(text=f"监控中 · {interval:g}s")
        self.log(f"开始监控：{self.tree.item(aid, 'text')} / {role['name']} / 每 {interval:g}s")
        self.watch_thread = threading.Thread(
            target=self._watch_loop, args=(aid, role["roleId"], role["name"], interval), daemon=True)
        self.watch_thread.start()

    def _watch_loop(self, aid: str, role_id: str, role_name: str, interval: float):
        last_msg = None
        while not self.watch_stop.is_set():
            try:
                d = fetch_detail(self.state, aid)
                roles = roles_of(d)
                role = next((r for r in roles if r["roleId"] == role_id), None)
                if not role:
                    self.log("监控的角色不存在了，停止。")
                    break
                if role["limit"] is None:
                    free = True
                else:
                    free = role["used"] < role["limit"]
                now = time.time() * 1000
                opened = not d.get("supBeginTime") or now >= d.get("supBeginTime")
                if free and opened:
                    if self.auto_var.get():
                        status, raw = sign_up(self.state, aid, role_id)
                        if status == 200:
                            self.log("★ 抢到了！已提交报名。")
                            beep()
                            break
                        self.log(f"有名额但提交失败：{status} {raw[:120]}")
                    else:
                        if last_msg != "free":
                            self.log(f"有名额（剩 {max(0, (role['limit'] or 0) - role['used'])}），未开自动报名。")
                            last_msg = "free"
                        beep()
                else:
                    if last_msg != "full":
                        self.log(f"暂无名额（{role['used']}/{role['limit']}）。")
                        last_msg = "full"
            except ApiError as e:
                self.log(f"监控请求失败：{e}")
                if e.status == 401:
                    self.log("登录已过期，请重新登录。")
                    break
            except Exception as e:
                self.log(f"监控异常：{type(e).__name__}: {e}")
            time.sleep(interval)
        self.watch_stop.set()
        try:
            self.root.after(0, lambda: self.watch_btn.configure(text="开始监控"))
            self.root.after(0, lambda: self.watch_label.configure(text="已停止"))
        except Exception:
            pass


# --------------------------------------------------------------------------
# 自检 / 入口
# --------------------------------------------------------------------------
def selftest() -> int:
    ok = 0
    total = 0

    def check(name, cond, extra=""):
        nonlocal ok, total
        total += 1
        if cond:
            ok += 1
            print(f"  ok   {name}")
        else:
            print(f"  FAIL {name} {extra}")

    got = sign(VECTOR_URL, "", VECTOR_TS, VECTOR_NONCE)
    check("签名与真实抓包样本一致", got == VECTOR_HEADER, got[:24])
    check("token 参与拼接", sign(VECTOR_URL, "abc", VECTOR_TS, VECTOR_NONCE) != got)
    check("换 URL 签名变化", sign(VECTOR_URL + "/x", "", VECTOR_TS, VECTOR_NONCE) != got)

    info = parse_lg_info(json.dumps({"token": "t", "userId": "u", "classId": "c"}))
    check("lgInfo 解析", info == {"token": "t", "userId": "u", "classId": "c"})
    check("lgInfo 缺字段返回 None", parse_lg_info("{}") is None)

    st = load_state()
    print(f"  info 本机登录：{'有' if st.get('token') else '无'}（{st.get('savedAt', '—')}）")

    print(f"RESULT: {'PASS' if ok == total else 'FAIL'}  {ok}/{total}")
    return 0 if ok == total else 1


def smoke() -> int:
    if tk is None:
        print("没有 tkinter，无法开界面")
        return 1
    root = tk.Tk()
    App(root)
    root.after(1200, root.destroy)
    root.mainloop()
    print("GUI smoke OK")
    return 0


def main() -> int:
    if "--selftest" in sys.argv:
        return selftest()
    if "--smoke" in sys.argv:
        return smoke()
    if tk is None:
        print("缺少 tkinter（Python 安装时勾选 tcl/tk）")
        return 1
    root = tk.Tk()
    App(root)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
