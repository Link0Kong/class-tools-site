# -*- coding: utf-8 -*-
"""sync.py — 教务系统课表同步 CLI（可被 Windows 计划任务调用）。

链路（2026-11-03 起）：学校统一身份认证（authserver）→ 门户 e.fjtcm.edu.cn
→「新教务系统」SSO → http://210.34.74.77 周课表（qz-weeklyTable）。

常用命令（cwd = web\\jwxt）：
    python sync.py --save-creds                      # 交互录入统一认证账号/密码，DPAPI 加密保存
    python sync.py --check                           # 只验证 SSO 全链路是否可用
    python sync.py                                   # SSO -> 抓课表 -> 写 ../tools/tt.json
    python sync.py --publish-link --copy             # 额外输出/复制 #tt= 发布链接
    python sync.py --deploy                          # 写完后调用 deploy/sync_tools.py 上传 tt.json
    python sync.py --manual                          # 人工辅助：可见 Edge 手动登录后自动抓
    python sync.py --direct                          # 旧的 jsxsd 直登（仅调试，通常已不可用）

CloudBase（2026-11-07 起，DNS 暂停改造）：每次成功写盘后自动把 tt.json 快照发布到云端
`public.site_assets` 行 id='tt'（实现见 tt_cloud.py），供站点域名暂停后小程序/网页读取；
该步骤失败只记日志，不影响退出码与 --deploy 的 OSS 上传。

退出码：0 成功 / 2 登录失败 / 3 抓取、解析或上传失败。
"""

import argparse
import datetime
import getpass
import json
import os
import re
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import jwxt  # noqa: E402

logger = jwxt.logger

EXIT_OK = 0
EXIT_LOGIN = 2
EXIT_FETCH = 3

DEFAULT_TERM = "2026-2027-1"
DEFAULT_OUT = os.path.abspath(os.path.join(HERE, "..", "tools", "tt.json"))
DEPLOY_SCRIPT = os.path.abspath(os.path.join(HERE, "..", "deploy", "sync_tools.py"))


class _Parser(argparse.ArgumentParser):
    """参数错误统一 exit 1，避免和「登录失败 exit 2」混淆。"""

    def error(self, message):
        self.print_usage(sys.stderr)
        sys.stderr.write("参数错误：%s\n" % message)
        sys.exit(1)


def build_parser() -> argparse.ArgumentParser:
    p = _Parser(
        prog="sync.py",
        description=("班级工具站 · 教务课表同步（学校统一身份认证 authserver → 门户 → 新教务系统 "
                     "http://210.34.74.77，周表 qz-weeklyTable）"),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "凭据：默认读取本目录 creds.dpapi（Windows DPAPI 加密，仅当前用户可解）。\n"
            "注意：密码是**学校统一身份认证密码**（不是旧 jsxsd 直登密码）。\n"
            "密码永远不会写进日志/明文文件；首次使用请先 --save-creds。\n"
            "示例：\n"
            "  python sync.py --save-creds --account <学号>\n"
            "  python sync.py --check\n"
            "  python sync.py --out ../tools/tt.json --term 2026-2027-1 --term-start 2026-08-31 --deploy\n"
            "  python sync.py --refresh-sso          # 忽略 cookie 缓存，强制重新走统一认证\n"
            "  python sync.py --manual               # 自动流程不行时，用可见浏览器手动登录\n"
        ),
    )
    p.add_argument("--check", action="store_true",
                   help="只验证 SSO 登录链路是否可用（成功 exit 0，失败 exit 2）")
    p.add_argument("--save-creds", action="store_true",
                   help="交互输入统一认证账号/密码并 DPAPI 加密保存，然后退出")
    p.add_argument("--account", default="",
                   help="学号（统一认证账号；不填则用已保存凭据里的账号）")
    p.add_argument("--password-stdin", action="store_true",
                   help="从标准输入第一行读密码（仅自动化测试；日常请用 --save-creds）")
    p.add_argument("--term", default=DEFAULT_TERM,
                   help="学期，格式 YYYY-YYYY-1|2（默认 %s）" % DEFAULT_TERM)
    p.add_argument("--term-start", default="",
                   help="学期第 1 周周一日期 YYYY-MM-DD（不填则沿用已有 tt.json / 按学期推断）")
    p.add_argument("--out", default=DEFAULT_OUT,
                   help="输出 JSON 路径（默认 ../tools/tt.json）")
    p.add_argument("--publish-link", action="store_true",
                   help="输出 https://tool.furina.fun/#tt=<base64url({c,t})> 发布链接")
    p.add_argument("--copy", action="store_true",
                   help="把发布链接复制到剪贴板（Windows）")
    p.add_argument("--deploy", action="store_true",
                   help="写完后调用 ../deploy/sync_tools.py 上传 tt.json")
    p.add_argument("--manual", action="store_true",
                   help="人工辅助模式：用可见 Edge 打开统一认证，手动登录后自动抓课表")
    p.add_argument("--manual-timeout", type=int, default=300,
                   help="人工辅助模式等待登录的秒数（默认 300）")
    p.add_argument("--browser", default="",
                   help="指定 Edge/Chrome 的 exe（默认自动查找）")
    p.add_argument("--direct", action="store_true",
                   help="走旧版 jsxsd 直登（调试用；学校已切统一认证，通常不可用）")
    p.add_argument("--refresh-sso", action="store_true",
                   help="忽略本地 cookie 缓存，强制重新走统一认证 SSO")
    p.add_argument("--day-order", default="column", choices=("column", "header"),
                   help="周表星期映射：column=按数据列位置（默认，col1=周一）；"
                        "header=按 th 文本（仅调试，教务页表头有 bug）")
    p.add_argument("--quiet", action="store_true", help="只写日志文件，不打印到控制台")
    p.add_argument("--verbose", action="store_true", help="日志输出 DEBUG 细节")
    return p


# ---------------------------------------------------------------------------
# 凭据
# ---------------------------------------------------------------------------

def _can_prompt() -> bool:
    try:
        return sys.stdin is not None and sys.stdin.isatty() and sys.stderr is not None
    except Exception:
        return False


def _read_password(args):
    if args.password_stdin:
        line = sys.stdin.readline() if sys.stdin else ""
        password = (line or "").rstrip("\r\n")
        if not password:
            raise jwxt.LoginError("--password-stdin 没有读到密码")
        return password
    env_password = os.environ.get("JWXT_PASSWORD")
    if env_password:
        logger.warning("使用环境变量 JWXT_PASSWORD（仅建议调试用）")
        return env_password
    if _can_prompt():
        return getpass.getpass("统一认证密码（输入不回显）：")
    raise jwxt.LoginError("没有可用密码：请先运行 python sync.py --save-creds")


def resolve_credentials(args):
    """返回 (account, password)。优先级：命令行账号 > 已保存凭据；密码优先用已保存的。"""
    account = (args.account or os.environ.get("JWXT_ACCOUNT") or "").strip()
    password = None
    try:
        saved = jwxt.load_credentials()
    except jwxt.JwxtError as exc:
        logger.warning("已保存凭据不可用：%s（继续使用参数/交互输入）", exc)
        saved = None
    if saved:
        if account and account != saved[0]:
            logger.warning("命令行账号 %s 与已保存凭据的账号 %s 不一致：仍用已保存密码，"
                           "如要换号请重新 --save-creds", jwxt.mask_account(account),
                           jwxt.mask_account(saved[0]))
        account = account or saved[0]
        password = saved[1]
        logger.info("使用已保存的 DPAPI 凭据（account=%s）", jwxt.mask_account(account))
    if password is None:
        password = _read_password(args)
    if not account:
        if _can_prompt():
            account = input("学号：").strip()
        if not account:
            raise jwxt.LoginError("缺少账号：请加 --account，或先运行 --save-creds")
    return account, password


def do_save_creds(args) -> int:
    """交互录入统一认证账号密码，DPAPI 加密保存后退出（不在这里试登录，避免无谓的失败计数）。"""
    if not _can_prompt():
        raise jwxt.JwxtError("--save-creds 需要在交互终端里运行（密码用 getpass 隐藏输入）")
    account = (args.account or "").strip()
    if not account:
        account = input("学号（学校统一身份认证账号）：").strip()
    if not account:
        raise jwxt.JwxtError("账号为空：请重新运行并输入学号")
    print("提示：这里要输入的是**学校统一身份认证（authserver）密码**，不是旧教务系统直登密码。")
    password = getpass.getpass("统一认证密码（输入不回显）：")
    if not password:
        raise jwxt.JwxtError("密码为空")
    confirm = getpass.getpass("再输一次确认：")
    if password != confirm:
        raise jwxt.JwxtError("两次输入的密码不一致")
    jwxt.save_credentials(account, password)
    print("OK 凭据已加密保存：%s" % jwxt.credentials_path())
    print("   （Windows DPAPI，仅当前 Windows 用户可解密；不要上传网盘/不要进 Git）")
    print("   下一步：python sync.py --check")
    return EXIT_OK


# ---------------------------------------------------------------------------
# 学期起始日
# ---------------------------------------------------------------------------

def _first_monday(day: datetime.date) -> datetime.date:
    return day + datetime.timedelta(days=(7 - day.weekday()) % 7)


def resolve_term_start(explicit: str, term: str, out_path: str = DEFAULT_OUT) -> str:
    """优先命令行；其次已有 tt.json 的 t；最后按学期推断（并警告）。"""
    value = jwxt.normalize_term_start(explicit)
    if value:
        return value
    try:
        if out_path and os.path.isfile(out_path):
            with open(out_path, "r", encoding="utf-8") as f:
                old = json.load(f)
            value = jwxt.normalize_term_start(old.get("t"))
            if value:
                logger.info("沿用已有输出文件里的学期起始日：%s", value)
                return value
    except (OSError, ValueError):
        pass
    m = re.match(r"(\d{4})-(\d{4})-([12])", term or "")
    if m:
        season = m.group(3)
        if season == "1":
            base = datetime.date(int(m.group(1)), 9, 1)
        else:
            base = datetime.date(int(m.group(2)), 2, 17)
        guess = _first_monday(base)
        logger.warning(
            "未指定 --term-start，按 %s 学期推断为 %s（若与实际不符请手动指定）",
            "秋" if season == "1" else "春", guess.isoformat(),
        )
        print("提示：未指定 --term-start，已按学期推断为 %s" % guess.isoformat())
        return guess.isoformat()
    logger.warning("未指定 --term-start 且无法从学期推断，t 将为空（站点不显示周次）")
    return ""


# ---------------------------------------------------------------------------
# 输出 & 部署
# ---------------------------------------------------------------------------

def write_output(out_path: str, parsed: dict, term: str, term_start: str) -> dict:
    """写站点同源可 fetch 的 tt.json（结构由 Lead 定）。"""
    courses = jwxt.clean_courses(parsed.get("c"))
    if not courses:
        raise jwxt.ParseError("清洗后没有可用课程")
    doc = {
        "c": courses,
        "t": term_start or parsed.get("t") or "",
        "meta": {
            "fetchedAt": int(time.time() * 1000),
            "term": term,
            "source": "jwxt",
            "count": len(courses),
        },
    }
    path = os.path.abspath(out_path)
    folder = os.path.dirname(path)
    if folder:
        os.makedirs(folder, exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        json.dump(doc, f, ensure_ascii=False, indent=2)
        f.write("\n")
    os.replace(tmp, path)
    size = os.path.getsize(path)
    logger.info("已写入课表：%s（%d 门课，%d 字节，t=%s）", path, len(courses), size, doc["t"])
    print("OK 已写入 %s（%d 门课，t=%s）" % (path, len(courses), doc["t"]))
    return doc


def publish_cloud(out_path: str) -> None:
    """把课表快照发布到 CloudBase site_assets 行 id='tt'（2026-11-07 DNS 暂停改造）。

    契约：dns_pause_tt_health_spec.md §3 —— 写盘成功后**总是尝试**发布；失败只记日志，
    **不得改变 sync.py 退出码、不影响 --deploy 的 OSS 上传**。token 处理全部在 tt_cloud 内。
    """
    try:
        import tt_cloud  # 同目录；惰性导入，避免该模块异常时拖垮整条同步链路
        result = tt_cloud.publish(out_path)
        logger.info(
            "云端课表快照已发布：count=%s termStart=%s method=%s %sms（校验=%s）",
            result.get("count"), result.get("termStart") or "-",
            result.get("method"), result.get("ms"),
            "ok" if result.get("verified") else "mismatch",
        )
    except Exception:
        logger.warning("云端课表快照发布失败（不影响本地文件与 OSS 上传）", exc_info=True)


def deploy_output(out_path: str) -> bool:
    """调用 Lead 的 deploy/sync_tools.py 把 tt.json 同步到线上站根目录。"""
    if not os.path.isfile(DEPLOY_SCRIPT):
        logger.error("找不到部署脚本：%s", DEPLOY_SCRIPT)
        return False
    name = os.path.basename(out_path)
    logger.info("调用部署脚本：%s %s", DEPLOY_SCRIPT, name)
    try:
        env = dict(os.environ)
        env["PYTHONIOENCODING"] = "utf-8"   # 子进程(pythonw)默认 cp936，统一成 UTF-8 才不乱码
        proc = subprocess.run(
            [sys.executable, DEPLOY_SCRIPT, name],
            cwd=os.path.dirname(DEPLOY_SCRIPT),
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=180,
            env=env,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        logger.error("部署脚本执行失败：%s", exc)
        return False
    for line in (proc.stdout or "").splitlines():
        logger.info("deploy | %s", line.strip())
    if proc.returncode != 0:
        logger.error("部署失败（exit %s）：%s", proc.returncode, (proc.stderr or "").strip())
        return False
    stdout = proc.stdout or ""
    if name not in stdout:
        logger.warning(
            "部署脚本执行成功，但输出里没有 %s 的上传记录（检查 deploy/sync_tools.py 的文件列表）",
            name,
        )
    return True


def emit_publish_link(courses, term_start: str, copy: bool) -> str:
    url = jwxt.build_publish_url(courses, term_start)
    print(url)
    logger.info("发布链接已生成：%d 字符", len(url))
    if copy:
        ok = jwxt.copy_to_clipboard(url)
        logger.info("复制到剪贴板：%s", "成功" if ok else "失败")
        print("已复制到剪贴板" if ok else "复制失败（可手动选中上面的链接复制）")
    return url


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------

def run(args) -> int:
    if args.save_creds:
        return do_save_creds(args)

    # ---- 人工辅助模式：可见浏览器里手动登录（不需要密码本）----
    if args.manual:
        cookies = jwxt.manual_get_jwxt_cookies(
            login_timeout=args.manual_timeout,
            browser=args.browser or None,
        )
        jwxt.save_jwxsd_cookies(cookies)
        session = jwxt.session_from_cookies(cookies)
        if args.check:
            print("OK 手动登录成功：教务系统可访问（cookie 已缓存）")
            logger.info("--check（manual）通过")
            return EXIT_OK
        return sync_from_session(args, session, account="", password=None)

    # ---- 自动模式：统一认证 SSO（默认）/ 旧 jsxsd 直登（--direct，调试用）----
    account, password = resolve_credentials(args)
    if args.direct:
        logger.warning("--direct：走旧版 jsxsd 直登（仅调试；学校已切统一认证，通常不可用）")
        session = jwxt.login(account, password)
    else:
        session = jwxt.sso_login(account, password, force=args.refresh_sso)
    if args.check:
        how = "旧版 jsxsd 直登" if args.direct else "统一认证 SSO"
        print("OK %s 登录成功：account=%s，教务系统可访问（xsMainV.jsp 正常）"
              % (how, jwxt.mask_account(account)))
        logger.info("--check 通过：%s", how)
        return EXIT_OK

    try:
        return sync_from_session(args, session, account=account, password=password)
    except jwxt.LoginError as exc:
        if args.direct or not password:
            raise
        logger.warning("教务系统会话失效（%s），强制重新 SSO 后重试一次…", exc)
        session = jwxt.sso_login(account, password, force=True)
        return sync_from_session(args, session, account=account, password=password)


def sync_from_session(args, session, *, account: str = "", password: str = None) -> int:
    term_start = resolve_term_start(args.term_start, args.term, os.path.abspath(args.out))
    logger.info("开始抓取课表：term=%s", args.term)
    try:
        html = jwxt.fetch_timetable(session, args.term)
        parsed = jwxt.parse_timetable(html, term_start, day_order=args.day_order)
    except (jwxt.FetchError, jwxt.ParseError) as first_exc:
        logger.warning("HTML 课表抓取/解析失败：%s；尝试 app.do JSON 兜底", first_exc)
        items = jwxt.fetch_timetable_json(session, account, args.term) if account else None
        if not items:
            raise
        parsed = jwxt.parse_api_timetable(items, term_start)
    return finish(args, parsed, term_start)


def finish(args, parsed: dict, term_start: str) -> int:
    doc = write_output(args.out, parsed, args.term, term_start)
    publish_cloud(args.out)  # 云端课表快照（失败只记日志，不影响退出码/部署）
    if args.publish_link or args.copy:
        emit_publish_link(doc["c"], doc["t"], args.copy)
    if args.deploy:
        if not deploy_output(args.out):
            logger.error("tt.json 已写好，但上传失败；可稍后手动执行 deploy/sync_tools.py")
            return EXIT_FETCH
    logger.info("同步完成：%d 门课", len(doc["c"]))
    return EXIT_OK


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    log_path = jwxt.setup_logger(verbose=args.verbose, quiet=args.quiet)
    logger.debug("日志文件：%s", log_path)
    try:
        return run(args)
    except jwxt.LoginError as exc:
        logger.error("登录失败：%s", exc)
        if not args.quiet:
            print("FAIL 登录失败：%s" % exc, file=sys.stderr)
        return EXIT_LOGIN
    except (jwxt.FetchError, jwxt.ParseError, jwxt.JwxtError) as exc:
        logger.error("抓取/解析失败：%s", exc)
        if not args.quiet:
            print("FAIL %s" % exc, file=sys.stderr)
        return EXIT_FETCH
    except KeyboardInterrupt:
        logger.error("用户取消")
        return EXIT_FETCH
    except Exception:
        logger.exception("未预期错误")
        return EXIT_FETCH


if __name__ == "__main__":
    sys.exit(main())
