# -*- coding: utf-8 -*-
"""推送适配器：PushPlus / 企业微信群机器人 / Server酱 / 通用 webhook / QQ邮箱 SMTP。

设计原则：
- 全部**可选**：config.json 里配哪个用哪个；一个都没配 → 只写日志，不报错。
- 单渠道失败不影响其它渠道，也不影响主流程（send() 永不抛异常）。
- 日志不出现 webhook key / 邮箱授权码 / 完整收件地址（由 util.mask_url / util.scrub 兜底）。

本文件是本地化新增代码（非 jialiangh 原项目），MIT 许可，见 NOTICE。
"""
from __future__ import annotations

import json
import os
import re
import smtplib
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from email.header import Header
from email.mime.text import MIMEText
from email.utils import formataddr, formatdate
from html import unescape as _html_unescape

import util

TIMEOUT = 20
PUSHPLUS_API = "https://www.pushplus.plus/send"
SERVERCHAN_API = "https://sctapi.ftqq.com/{sendkey}.send"
WECOM_MAX_BYTES = 4000          # 企业微信 markdown 上限 4096 字节，留余量
CHANNEL_ORDER = ("pushplus", "wecom", "serverchan", "webhook", "email")

_EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}$")


# -------------------------------------------------------- HTML 转纯文本 ---
_BR_RE = re.compile(r"(?i)<br\s*/?>")
_CELL_END_RE = re.compile(r"(?i)</(?:td|th)>")
_BLOCK_END_RE = re.compile(r"(?i)</(?:p|div|tr|h[1-6]|li|table|blockquote|section|article)>")
_TAG_RE = re.compile(r"<[^>]+>")
_MULTI_SPACE_RE = re.compile(r"[ \t]{2,}")
_TRAIL_PIPE_RE = re.compile(r"\s*\|\s*$")
_BLANK_LINES_RE = re.compile(r"\n{3,}")


def html_to_text(html_content):
    """把推送用的 HTML 变成可读纯文本（给企业微信/短信/邮件纯文本兜底）。"""
    if not html_content:
        return ""
    text = str(html_content)
    text = _BR_RE.sub("\n", text)
    text = _CELL_END_RE.sub(" | ", text)
    text = _BLOCK_END_RE.sub("\n", text)
    text = _TAG_RE.sub("", text)
    text = _html_unescape(text).replace("\xa0", " ")
    lines = []
    for line in text.splitlines():
        line = _MULTI_SPACE_RE.sub(" ", line).strip()
        line = _TRAIL_PIPE_RE.sub("", line).strip()
        if line:
            lines.append(line)
    return _BLANK_LINES_RE.sub("\n\n", "\n".join(lines)).strip()


def message_text(title, html_content):
    """标题 + 纯文本正文（日志 / 通用 webhook / dry-run 预览用）。"""
    body = html_to_text(html_content)
    return title if not body else "%s\n%s" % (title, body)


def truncate_utf8(text, limit):
    """按 UTF-8 字节数截断，避免企业微信 4096 字节上限报错。"""
    data = str(text).encode("utf-8")
    if len(data) <= limit:
        return str(text)
    marker = "\n…（内容过长，已截断）"
    budget = max(0, limit - len(marker.encode("utf-8")))
    return data[:budget].decode("utf-8", "ignore") + marker


# ------------------------------------------------------------- 配置读取 ---
def _push_cfg(cfg):
    section = (cfg or {}).get("push")
    return section if isinstance(section, dict) else {}


def _channel_cfg(cfg, name):
    section = _push_cfg(cfg).get(name)
    return section if isinstance(section, dict) else {}


def _first(*values):
    for value in values:
        if value not in (None, "", [], {}):
            return value
    return None


def _env(name):
    return os.environ.get(name) or None


def _looks_like_email(value):
    return bool(_EMAIL_RE.match(str(value or "").strip()))


def pushplus_token(cfg):
    return _first(_channel_cfg(cfg, "pushplus").get("token"),
                  (cfg or {}).get("pushplus_token"),
                  _env("PUSHPLUS_TOKEN"))


def wecom_webhook(cfg):
    return _first(_channel_cfg(cfg, "wecom").get("webhook"),
                  _channel_cfg(cfg, "wecom").get("url"),
                  _env("WECOM_WEBHOOK"))


def serverchan_sendkey(cfg):
    return _first(_channel_cfg(cfg, "serverchan").get("sendkey"),
                  _channel_cfg(cfg, "serverchan").get("key"),
                  _env("SERVERCHAN_SENDKEY"))


def webhook_url(cfg):
    return _first(_channel_cfg(cfg, "webhook").get("url"),
                  _env("PUSH_WEBHOOK_URL"))


def email_config(cfg):
    """合并 config 与 SMTP_* 环境变量；返回 dict（不含日志输出）。"""
    raw = _channel_cfg(cfg, "email")
    merged = {
        "smtp_host": _first(raw.get("smtp_host"), _env("SMTP_HOST"), "smtp.qq.com"),
        "smtp_port": _first(raw.get("smtp_port"), _env("SMTP_PORT"), 465),
        "ssl": raw.get("ssl", True),
        "user": _first(raw.get("user"), _env("SMTP_USER")),
        "password": _first(raw.get("password"), _env("SMTP_PASSWORD")),
        "to": _first(raw.get("to"), _env("SMTP_TO")),
        "from_name": _first(raw.get("from_name"), "电费监控"),
    }
    if isinstance(merged["to"], str):
        merged["to"] = [item.strip() for item in re.split(r"[,;]", merged["to"])
                        if item.strip()]
    elif isinstance(merged["to"], list):
        merged["to"] = [str(item).strip() for item in merged["to"] if str(item).strip()]
    else:
        merged["to"] = []
    return merged


def _is_configured(name, cfg):
    if name == "pushplus":
        token = pushplus_token(cfg)
        return bool(token) and not util.is_placeholder_text(token)
    if name == "wecom":
        url = str(wecom_webhook(cfg) or "")
        return url.startswith("http") and "key=" in url
    if name == "serverchan":
        key = serverchan_sendkey(cfg)
        return bool(key) and not util.is_placeholder_text(key)
    if name == "webhook":
        return str(webhook_url(cfg) or "").startswith("http")
    if name == "email":
        email = email_config(cfg)
        if not email["user"] or not email["password"] or not email["to"]:
            return False
        if util.is_placeholder_text(email["password"]):
            return False
        return _looks_like_email(email["user"]) and all(
            _looks_like_email(item) for item in email["to"])
    return False


def resolve_channels(cfg):
    """返回本次要用的渠道名列表（已配置的才返回；空列表 = 只写日志）。"""
    configured = [name for name in CHANNEL_ORDER if _is_configured(name, cfg)]
    chosen = _push_cfg(cfg).get("channels") or []
    if isinstance(chosen, str):
        chosen = [item.strip() for item in re.split(r"[,;]", chosen) if item.strip()]
    chosen = [str(item).strip().lower() for item in chosen if str(item).strip()]
    if chosen:
        return [name for name in chosen if name in configured]
    return configured


def missing_channels(cfg):
    """config 里显式点名但没配好的渠道（doctor 用来提示）。"""
    chosen = _push_cfg(cfg).get("channels") or []
    if isinstance(chosen, str):
        chosen = [item.strip() for item in re.split(r"[,;]", chosen) if item.strip()]
    configured = set(resolve_channels(cfg))
    return [str(item).strip().lower() for item in chosen
            if str(item).strip().lower() not in configured]


def describe(cfg):
    """给 status / doctor 的一句话描述（不含任何密钥）。"""
    channels = resolve_channels(cfg)
    return "、".join(channels) if channels else "未配置（只写日志，不报错）"


# ------------------------------------------------------------- 消息构造 ---
def wecom_content(title, html_content):
    body = html_to_text(html_content)
    content = "**%s**" % title if not body else "**%s**\n%s" % (title, body)
    return truncate_utf8(content, WECOM_MAX_BYTES)


def email_message(title, html_content, cfg):
    """构造 QQ 邮箱（或任意 SMTP）邮件，返回 (MIMEText, from_addr, to_list)。"""
    email = email_config(cfg)
    body = str(html_content or "")
    message = MIMEText(body, "html", "utf-8")
    message["Subject"] = Header(str(title), "utf-8").encode()
    message["From"] = formataddr((str(Header(str(email["from_name"]), "utf-8")),
                                  str(email["user"])))
    message["To"] = ", ".join(email["to"])
    message["Date"] = formatdate(localtime=True)
    return message, str(email["user"]), list(email["to"])


def build_request(channel, title, html_content, cfg):
    """构造单渠道请求（不发送）。测试与 dry-run 用；返回值含密钥，禁止打印。"""
    title = str(title or "")[:100]
    if channel == "pushplus":
        payload = {
            "token": pushplus_token(cfg),
            "title": title,
            "content": str(html_content or ""),
            "template": "html",
            "channel": "wechat",
        }
        return {
            "channel": "pushplus",
            "kind": "http",
            "url": PUSHPLUS_API,
            "method": "POST",
            "headers": {"Content-Type": "application/json; charset=utf-8"},
            "body": json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            "summary": "pushplus",
        }
    if channel == "wecom":
        content = wecom_content(title, html_content)
        payload = {"msgtype": "markdown", "markdown": {"content": content}}
        return {
            "channel": "wecom",
            "kind": "http",
            "url": wecom_webhook(cfg),
            "method": "POST",
            "headers": {"Content-Type": "application/json; charset=utf-8"},
            "body": json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            "summary": "markdown %d 字节" % len(content.encode("utf-8")),
        }
    if channel == "serverchan":
        key = serverchan_sendkey(cfg)
        body = urllib.parse.urlencode({
            "title": title,
            "desp": str(html_content or ""),
        }).encode("utf-8")
        return {
            "channel": "serverchan",
            "kind": "http",
            "url": SERVERCHAN_API.format(sendkey=key),
            "method": "POST",
            "headers": {"Content-Type": "application/x-www-form-urlencoded; charset=utf-8"},
            "body": body,
            "summary": "serverchan",
        }
    if channel == "webhook":
        webhook = _channel_cfg(cfg, "webhook")
        payload = {
            "title": title,
            "content": str(html_content or ""),
            "text": message_text(title, html_content),
            "ts": int(time.time()),
        }
        fmt = str(webhook.get("format") or "json").lower()
        if fmt == "form":
            body = urllib.parse.urlencode(payload).encode("utf-8")
            headers = {"Content-Type": "application/x-www-form-urlencoded; charset=utf-8"}
        else:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            headers = {"Content-Type": "application/json; charset=utf-8"}
        for key, value in (webhook.get("headers") or {}).items():
            if str(key).lower() in ("host", "content-length", "content-type"):
                continue
            headers[str(key)] = str(value)
        return {
            "channel": "webhook",
            "kind": "http",
            "url": webhook_url(cfg),
            "method": "POST",
            "headers": headers,
            "body": body,
            "summary": "webhook %s" % fmt,
        }
    if channel == "email":
        email = email_config(cfg)
        message, from_addr, to_list = email_message(title, html_content, cfg)
        return {
            "channel": "email",
            "kind": "smtp",
            "host": str(email["smtp_host"]),
            "port": int(email["smtp_port"] or 465),
            "ssl": bool(email["ssl"]),
            "user": str(email["user"]),
            "password": str(email["password"]),
            "from_addr": from_addr,
            "to": to_list,
            "message": message.as_string(),
            "summary": "邮件 → %s" % util.mask_email(", ".join(to_list)),
        }
    raise ValueError("未知推送渠道：%s" % channel)


# --------------------------------------------------------------- 发送 -----
def _json_or_raise(text):
    try:
        return json.loads(text)
    except ValueError:
        raise RuntimeError("返回非 JSON：%s" % util.scrub(text[:120]))


def _smtp_send(request):
    context = ssl.create_default_context()
    timeout = TIMEOUT
    if request.get("ssl", True):
        server = smtplib.SMTP_SSL(request["host"], request["port"],
                                  timeout=timeout, context=context)
    else:
        server = smtplib.SMTP(request["host"], request["port"], timeout=timeout)
    try:
        server.ehlo()
        if not request.get("ssl", True):
            try:
                server.starttls(context=context)
                server.ehlo()
            except smtplib.SMTPNotSupportedError:
                pass
        if request.get("user") and request.get("password"):
            server.login(request["user"], request["password"])
        server.sendmail(request["from_addr"], request["to"], request["message"])
    finally:
        try:
            server.quit()
        except Exception:
            pass
    return "邮件已投递 %d 位收件人" % len(request["to"])


def _execute(request):
    if request["kind"] == "smtp":
        return _smtp_send(request)
    http_request = urllib.request.Request(
        request["url"], data=request["body"], headers=request["headers"],
        method=request.get("method", "POST"))
    try:
        with urllib.request.urlopen(http_request, timeout=TIMEOUT) as response:
            status = getattr(response, "status", 200)
            raw = response.read(4096)
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            detail = exc.read().decode("utf-8", "replace")[:160]
        except Exception:
            pass
        raise RuntimeError("HTTP %s：%s" % (exc.code, util.scrub(detail) or exc.reason))
    except urllib.error.URLError as exc:
        raise RuntimeError("连不上：%s" % util.scrub(str(getattr(exc, "reason", exc))))

    text = raw.decode("utf-8", "replace")
    channel = request["channel"]
    if channel == "pushplus":
        payload = _json_or_raise(text)
        if str(payload.get("code")) != "200":
            raise RuntimeError("pushplus 返回异常：%s"
                               % util.compact({"code": payload.get("code"),
                                               "msg": payload.get("msg")}))
        return "pushplus code=200"
    if channel == "wecom":
        payload = _json_or_raise(text)
        if str(payload.get("errcode")) not in ("0", "None"):
            raise RuntimeError("企业微信返回 errcode=%s %s"
                               % (payload.get("errcode"), payload.get("errmsg")))
        return "企业微信 errcode=0"
    if channel == "serverchan":
        payload = _json_or_raise(text)
        if str(payload.get("code")) not in ("0", "200"):
            raise RuntimeError("Server酱返回 code=%s %s"
                               % (payload.get("code"),
                                  payload.get("message") or payload.get("msg")))
        return "Server酱成功"
    return "HTTP %s" % status


def send(title, html_content, cfg=None, dry=False):
    """推送到所有已配置渠道；永不抛异常。返回结果列表。

    未配置任何渠道时返回 [{"channel": "none", "ok": True, "detail": "仅写日志"}]。
    """
    cfg = cfg or {}
    channels = resolve_channels(cfg)
    if not channels:
        return [{"channel": "none", "ok": True,
                 "detail": "未配置推送渠道，仅写日志（不报错）"}]
    results = []
    if dry:
        for channel in channels:
            results.append({"channel": channel, "ok": True,
                            "detail": "dry-run，未发送"})
        return results
    for channel in channels:
        try:
            request = build_request(channel, title, html_content, cfg)
            detail = _execute(request)
            results.append({"channel": channel, "ok": True, "detail": detail})
        except Exception as exc:              # 单渠道失败不拖垮主流程
            detail = util.scrub("%s: %s" % (type(exc).__name__, exc))
            results.append({"channel": channel, "ok": False, "detail": detail})
    return results
