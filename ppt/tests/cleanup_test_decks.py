# -*- coding: utf-8 -*-
"""cleanup_test_decks.py — 交付前清理云端「演示」页的测试 deck（软删；默认只读演练）

背景
    ``public.ppt_decks`` 中 ``deleted=false`` 的行会出现在全班可见的网页「演示」页。
    ``tests/test_cloud_contract.py`` 会保留 2 个 ready fixture deck 供网页验收
    （标题「测试·嵌入视频演示」「测试·4:3 演示」），交付前必须软删，否则全班都看得到。

身份
    测试身份：学号 3260799999 / 姓名「测试账号」（公开文档里的测试身份，不是真实同学）。
    真实同学上传的 deck（如 dmwalrdlgevz90l）绝不触碰。

用法::

    # 默认 --dry-run：只读列出「将被软删」的测试 deck（id/标题/状态/创建时间），不写云端
    python tests/cleanup_test_decks.py

    # 真软删：PATCH ppt_decks?id=in.(...)&deleted=eq.false  body {"deleted": true}
    # 幂等（重跑 0 行、无写操作）；PATCH 前会重新 GET 目标行并断言 owner_sid 全为测试身份
    python tests/cleanup_test_decks.py --apply

    # 只读统计测试 deck 的 OSS 前缀（ppt/a/<id>/ 与 ppt/src/<id>/）对象数/字节数；
    # 只做 list_objects_v2 分页统计，**不删除任何 OSS 对象**
    python tests/cleanup_test_decks.py --report-oss              # 当前可见（deleted=false）测试 deck
    python tests/cleanup_test_decks.py --report-oss --all-test   # 全部测试身份 deck（含已软删）

    # 组合：软删后立刻只读统计本次目标 deck 的 OSS 占用
    python tests/cleanup_test_decks.py --apply --report-oss

验收口径（与网页一致）
    - ``--apply`` 后 admin GET ``ppt_decks?select=id,title,status,deleted&deleted=eq.false`` 只剩真实 deck；
    - 再用 ``tools/index.html`` 里的 ``LIST_SELECT``（运行时读取，只读）按
      ``deleted=eq.false&order=created_at.desc&limit=100`` 查询，确认网页列表同样只剩真实 deck。

安全（红线）
    * 云端读写只经 ``agent.Cloud``（管理员 token 自动读取/刷新，**绝不打印 token/publish key**）；
    * OSS 只读；凭据由 ``oss_upload.OssUploader`` 内部读取 ``creds.env``，本脚本不打印 AK/SK；
    * 只软删（``deleted=true``）：不 DELETE 行、不删 OSS、不改其他表；
    * 输出中真实同学的学号/姓名一律脱敏；测试身份 id/标题可以显示。

退出码：0=成功（含幂等 0 行）；1=读取/PATCH/复核失败或 OSS 统计失败。
"""
import argparse
import os
import re
import sys
import time
from datetime import datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
PPT_DIR = os.path.dirname(HERE)
WEB_ROOT = os.path.dirname(PPT_DIR)
if PPT_DIR not in sys.path:
    sys.path.insert(0, PPT_DIR)

import agent  # noqa: E402
import oss_upload  # noqa: E402

TEST_SID = "3260799999"
TEST_NAME = "测试账号"
TZ = timezone(timedelta(hours=8))

# deck id 契约：d + base36/字母数字；这里宽松到 [A-Za-z0-9_-]{1,64}，并禁止任何 URL 特殊字符
DECK_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
FIELD_SELECT = "id,title,owner_sid,owner_name,status,deleted,created_at"
PAGE_SIZE = 1000


class CleanupError(Exception):
    """清理流程中的可读错误（消息已脱敏，不含 token/密钥）。"""


def _silent(*_args, **_kwargs):
    """Cloud / OSS 内部日志静默（token 刷新等也不打印）。"""
    return None


def _utf8_stdout():
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass


def fmt_ms(ms):
    """云端毫秒时间戳 → 本地（+08:00）可读时间；异常原样返回。"""
    try:
        return datetime.fromtimestamp(int(ms) / 1000.0, tz=TZ).strftime("%Y-%m-%d %H:%M:%S")
    except (TypeError, ValueError, OSError):
        return str(ms or "")


def mask_sid(sid):
    sid = str(sid or "")
    # 测试身份是公开文档里的测试账号，可显示；真实同学学号只留前 3 位
    return TEST_SID if sid == TEST_SID else (sid[:3] + "***" if sid else "")


def mask_name(row):
    if str(row.get("owner_sid") or "") == TEST_SID:
        return TEST_NAME
    return "***" if row.get("owner_name") else ""


def is_test_row(row):
    return str(row.get("owner_sid") or "").strip() == TEST_SID


def is_deleted(row):
    return bool(row.get("deleted"))


def _assert(cond, msg):
    """显式断言（不用 assert，避免 python -O 下失效）→ CleanupError。"""
    if not cond:
        raise CleanupError(msg)


# ---------------------------------------------------------------------------
# 云端读取（只经 agent.Cloud）
# ---------------------------------------------------------------------------
def fetch_decks(cloud, visible_only=True):
    """分页读取 ppt_decks；visible_only=True 时只取 deleted=false（= 网页可见口径）。"""
    rows = []
    offset = 0
    while True:
        query = "ppt_decks?select=%s&order=created_at.asc&limit=%d&offset=%d" % (
            FIELD_SELECT, PAGE_SIZE, offset)
        if visible_only:
            query += "&deleted=eq.false"
        status, data = cloud.get(query)
        if status != 200 or not isinstance(data, list):
            raise CleanupError("读取 ppt_decks 失败：HTTP %s %s"
                               % (status, agent.sanitize(str(data), 200)))
        rows.extend(data)
        if len(data) < PAGE_SIZE:
            break
        offset += PAGE_SIZE
    return rows


def _read_web_list_select():
    """从 tools/index.html 提取网页列表用的 LIST_SELECT（只读；取不到则返回备用字段集）。"""
    path = os.path.join(WEB_ROOT, "tools", "index.html")
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            text = fh.read()
        match = re.search(r'var\s+LIST_SELECT\s*=\s*"([A-Za-z0-9_,]+)"', text)
        if match:
            return match.group(1), ""
    except OSError:
        pass
    return FIELD_SELECT, "（未取到 tools/index.html 的 LIST_SELECT，用最小字段集）"


def web_query_rows(cloud):
    """按网页列表完全一致的查询口径取一行数据（deleted=eq.false&order=created_at.desc&limit=100）。"""
    select, note = _read_web_list_select()
    status, data = cloud.get(
        "ppt_decks?select=%s&deleted=eq.false&order=created_at.desc&limit=100" % select)
    if status != 200 or not isinstance(data, list):
        raise CleanupError("网页口径查询失败：HTTP %s %s"
                           % (status, agent.sanitize(str(data), 200)))
    return data, note


# ---------------------------------------------------------------------------
# 输出
# ---------------------------------------------------------------------------
def print_deck_rows(rows, indent="  "):
    if not rows:
        print(indent + "(无)")
        return
    for row in rows:
        print("%sid=%-24s title=%s"
              % (indent, str(row.get("id") or ""), str(row.get("title") or "")))
        print("%s    status=%-8s created=%s deleted=%-5s owner=%s"
              % (indent, str(row.get("status") or ""), fmt_ms(row.get("created_at")),
                 "true" if is_deleted(row) else "false", mask_sid(row.get("owner_sid"))))


def print_visible_summary(rows, tag):
    tests = [r for r in rows if is_test_row(r)]
    others = [r for r in rows if not is_test_row(r)]
    print("[%s] deleted=false 共 %d 行：测试身份 %d 行；其他（真实/保留）%d 行"
          % (tag, len(rows), len(tests), len(others)))
    return tests, others


# ---------------------------------------------------------------------------
# --apply：软删（带写前断言 + 写后复核）
# ---------------------------------------------------------------------------
def _pre_patch_recheck(cloud, ids):
    """PATCH 前重新 GET 目标行：必须全部存在且 owner_sid 全为测试身份，否则中止。"""
    query = "ppt_decks?select=id,title,owner_sid,deleted&id=in.(%s)&limit=1000" % ",".join(ids)
    status, data = cloud.get(query)
    if status != 200 or not isinstance(data, list):
        raise CleanupError("写前复核 GET 失败：HTTP %s %s"
                           % (status, agent.sanitize(str(data), 200)))
    found = {str(r.get("id")): r for r in data}
    for deck_id in ids:
        _assert(deck_id in found, "写前复核：目标行丢失（可能被并发硬删）：%s；已中止，未写云端" % deck_id)
        _assert(is_test_row(found[deck_id]),
                "写前复核：目标行 owner_sid 不是测试身份 %s（实际 %r）→ 中止，防止误删真实 deck：%s"
                % (TEST_SID, mask_sid(found[deck_id].get("owner_sid")), deck_id))
    # 已不存在的（并发软删）/仍可见的分别处理
    still_visible = [deck_id for deck_id in ids if not is_deleted(found[deck_id])]
    already = [deck_id for deck_id in ids if is_deleted(found[deck_id])]
    return still_visible, already


def do_apply(cloud, targets, others_before):
    if not targets:
        print("[apply] 0 行测试 deck 需软删（幂等：跳过 PATCH，无写操作）")
        _post_verify(cloud, [], [r.get("id") for r in others_before])
        return 0

    print("[apply] 目标 %d 行（owner_sid=%s 且 deleted=false）：" % (len(targets), TEST_SID))
    print_deck_rows(targets)

    ids = [str(r.get("id") or "") for r in targets]
    for deck_id in ids:
        _assert(DECK_ID_RE.match(deck_id), "非法 deck id（含 URL 特殊字符），已中止：%r" % deck_id)

    still_visible, already = _pre_patch_recheck(cloud, ids)
    if already:
        print("[apply] 以下 deck 已被并发软删，跳过：%s" % ", ".join(already))
    if not still_visible:
        print("[apply] 0 行需写（目标均已被并发软删）")
        _post_verify(cloud, ids, [r.get("id") for r in others_before])
        return 0

    print("[apply] 写前断言通过：目标行 owner_sid 全为测试身份 %s（真实 deck 不参与）" % TEST_SID)
    patch_path = "ppt_decks?id=in.(%s)&deleted=eq.false" % ",".join(still_visible)
    print("[apply] PATCH %s  body={\"deleted\": true}" % patch_path)
    status, data = cloud.patch(patch_path, {"deleted": True},
                               prefer="return=representation")
    print("[apply] PATCH HTTP 状态：%s" % status)
    if not (200 <= int(status or 0) < 300):
        print("[apply] [ERROR] PATCH 失败，返回：%s" % agent.sanitize(str(data), 300))
        return 1
    if isinstance(data, list) and data:
        print("[apply] 受影响 %d 行：" % len(data))
        print_deck_rows(data)
    else:
        print("[apply] [WARN] PATCH 未返回受影响行（可能已被并发软删），以复核为准")

    return _post_verify(cloud, still_visible, [r.get("id") for r in others_before])


def _post_verify(cloud, patched_ids, others_before_ids):
    """软删后复核：admin GET + 网页 LIST_SELECT 口径查询，必须只剩真实 deck。"""
    rc = 0
    print("\n[verify] admin GET ppt_decks?select=id,title,status,deleted&deleted=eq.false")
    try:
        visible = fetch_decks(cloud, visible_only=True)
    except CleanupError as exc:
        print("[verify] [ERROR] %s" % exc)
        return 1
    tests = [r for r in visible if is_test_row(r)]
    others = [r for r in visible if not is_test_row(r)]
    print("[verify] 结果 %d 行（测试身份 %d 行，真实/保留 %d 行）："
          % (len(visible), len(tests), len(others)))
    print_deck_rows(others)
    if tests:
        rc = 1
        print("[verify] [ERROR] 仍有测试 deck 处于 deleted=false：%s"
              % ", ".join(str(r.get("id")) for r in tests))
    else:
        print("[verify] OK：deleted=false 已无测试 deck")

    # 写前存在、写后仍应存在的真实/保留行（若消失说明被其他进程改动，提示人工确认）
    after_ids = {str(r.get("id")) for r in visible}
    vanished = [str(i) for i in others_before_ids if i and str(i) not in after_ids]
    if vanished:
        print("[verify] [WARN] 以下真实/保留 deck 不再可见（非本脚本软删目标，请人工确认）：%s"
              % ", ".join(str(i) for i in vanished))

    if patched_ids:
        remaining = {str(r.get("id")) for r in tests}
        missed = [i for i in patched_ids if i in remaining]
        if missed:
            rc = 1
            print("[verify] [ERROR] 目标 id 仍在 deleted=false：%s" % ", ".join(missed))

    print("\n[verify] 网页列表口径查询（tools/index.html LIST_SELECT + deleted=eq.false"
          "&order=created_at.desc&limit=100）")
    try:
        web_rows, note = web_query_rows(cloud)
    except CleanupError as exc:
        print("[verify] [ERROR] %s" % exc)
        return 1
    web_tests = [r for r in web_rows if is_test_row(r)]
    web_others = [r for r in web_rows if not is_test_row(r)]
    print("[verify] 网页列表 %d 行（测试身份 %d 行，真实/保留 %d 行）%s"
          % (len(web_rows), len(web_tests), len(web_others), note))
    print_deck_rows(web_others)
    if web_tests:
        rc = 1
        print("[verify] [ERROR] 网页列表仍能看到测试 deck：%s"
              % ", ".join(str(r.get("id")) for r in web_tests))
    else:
        print("[verify] OK：网页列表只剩真实 deck")
    return rc


# ---------------------------------------------------------------------------
# --report-oss：只读统计 OSS 前缀（不删除）
# ---------------------------------------------------------------------------
def list_prefix_stats(bucket, prefix, retries=2):
    """list_objects_v2 分页统计某前缀：返回 (对象数, 总字节)。"""
    total = 0
    total_bytes = 0
    token = ""
    attempt = 0
    while True:
        kwargs = {"prefix": prefix, "max_keys": 1000}
        if token:
            kwargs["continuation_token"] = token
        try:
            result = bucket.list_objects_v2(**kwargs)
        except Exception:  # noqa: BLE001  网络抖动重试一次
            if attempt >= retries:
                raise
            attempt += 1
            time.sleep(0.6 * attempt)
            continue
        for obj in list(getattr(result, "object_list", None) or []):
            total += 1
            total_bytes += int(getattr(obj, "size", 0) or 0)
        if not getattr(result, "is_truncated", False):
            break
        token = str(getattr(result, "next_continuation_token", "") or "")
        if not token:
            break
    return total, total_bytes


def do_report_oss(deck_rows):
    print("\n[report-oss] 只读统计测试 deck 的 OSS 前缀（list_objects_v2 分页；不删除任何对象）")
    if not deck_rows:
        print("[report-oss] 无目标 deck：当前无可见测试 deck。")
        print("[report-oss] 可加 --all-test 统计全部测试身份 deck（含已软删），"
              "或在 --apply 前运行 / 用 --apply --report-oss 组合。")
        return 0
    try:
        bucket = oss_upload.OssUploader(log=_silent).bucket()
    except Exception as exc:  # noqa: BLE001  凭据/网络错误（消息不含 AK/SK）
        print("[report-oss] [ERROR] 初始化 OSS 失败：%s" % agent.sanitize(str(exc), 200))
        return 1

    failed = 0
    sum_a = [0, 0]
    sum_s = [0, 0]
    for row in deck_rows:
        deck_id = str(row.get("id") or "")
        if not DECK_ID_RE.match(deck_id):
            print("[report-oss] [WARN] 非法 deck id，跳过：%r" % deck_id)
            failed += 1
            continue
        print("[report-oss] id=%s title=%s deleted=%s"
              % (deck_id, str(row.get("title") or ""), "true" if is_deleted(row) else "false"))
        for label, prefix, acc in (("ppt/a", "ppt/a/%s/" % deck_id, sum_a),
                                   ("ppt/src", "ppt/src/%s/" % deck_id, sum_s)):
            try:
                count, size = list_prefix_stats(bucket, prefix)
            except Exception as exc:  # noqa: BLE001  只报告，不中断其他前缀
                failed += 1
                print("    [WARN] %s 列表失败：%s" % (prefix, agent.sanitize(str(exc), 200)))
                continue
            acc[0] += count
            acc[1] += size
            print("    %-8s %-28s %5d 个对象 / %s B" % (label, prefix, count, "{:,}".format(size)))

    total_count = sum_a[0] + sum_s[0]
    total_bytes = sum_a[1] + sum_s[1]
    print("[report-oss] ---- 合计（%d 个测试 deck）----" % len(deck_rows))
    print("[report-oss] ppt/a/    %5d 个对象 / %s B" % (sum_a[0], "{:,}".format(sum_a[1])))
    print("[report-oss] ppt/src/  %5d 个对象 / %s B" % (sum_s[0], "{:,}".format(sum_s[1])))
    print("[report-oss] 总计      %5d 个对象 / %s B（%s）"
          % (total_count, "{:,}".format(total_bytes),
             ("%.2f MiB" % (total_bytes / 1048576.0)) if total_bytes else "0 B"))
    print("[report-oss] 注意：本轮只统计、不删除；是否清理 OSS 由用户决定。")
    return 1 if failed else 0


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------
def build_parser():
    parser = argparse.ArgumentParser(
        description="交付前清理云端「演示」页的测试 deck（默认 dry-run；只软删，不删 OSS）")
    parser.add_argument("--apply", action="store_true",
                        help="执行软删（默认只读演练）；PATCH 前断言 owner_sid 全为测试身份")
    parser.add_argument("--report-oss", action="store_true",
                        help="只读统计测试 deck 的 OSS 前缀对象数/字节数（不删除）")
    parser.add_argument("--all-test", action="store_true",
                        help="配合 --report-oss：统计全部测试身份 deck（含已软删）")
    return parser


def main(argv=None):
    _utf8_stdout()
    args = build_parser().parse_args(argv)

    print("== 清理云端测试 PPT ==")
    print("测试身份：test_sid=%s / name=%s（真实同学 deck 不触碰）" % (TEST_SID, TEST_NAME))
    mode = "apply" if args.apply else "dry-run(只读)"
    if args.report_oss:
        mode += " + report-oss(只读)"
    print("模式：%s\n" % mode)

    try:
        cloud = agent.Cloud(log=_silent)
    except Exception as exc:  # noqa: BLE001  publish key/配置缺失（消息不含 token）
        print("[ERROR] 初始化云端客户端失败：%s" % agent.sanitize(str(exc), 200))
        return 1
    try:
        visible = fetch_decks(cloud, visible_only=True)
    except CleanupError as exc:
        print("[ERROR] %s" % exc)
        return 1

    targets, others = print_visible_summary(visible, "before")

    rc = 0
    if args.apply:
        print()
        rc = do_apply(cloud, targets, others)
    else:
        print("\n[dry-run] 只读演练，不写云端。将被软删的测试 deck（%d 行）：" % len(targets))
        print_deck_rows(targets)
        print("\n[dry-run] 保留的真实/其他 deck（%d 行）：" % len(others))
        print_deck_rows(others)
        print("\n[dry-run] 确认无误后运行：python tests/cleanup_test_decks.py --apply")

    report_rows = None
    if args.report_oss:
        if args.apply:
            # 本次软删的目标（即使刚被软删也统计）；若无目标则回退到当前可见测试 deck
            report_rows = targets if targets else []
        elif args.all_test:
            try:
                all_rows = fetch_decks(cloud, visible_only=False)
            except CleanupError as exc:
                print("[ERROR] %s" % exc)
                return 1
            report_rows = [r for r in all_rows if is_test_row(r)]
            print("\n[report-oss] 范围：全部测试身份 deck（含已软删）共 %d 行" % len(report_rows))
        else:
            report_rows = targets
        rc = do_report_oss(report_rows) or rc

    if rc == 0:
        print("\n完成：退出码 0")
    else:
        print("\n完成：退出码 1（见上方 ERROR）")
    return rc


if __name__ == "__main__":
    sys.exit(main())
