"""Exercise the public AI endpoint with the official test identity and synthetic text."""

import argparse
import json
import re
import sys
import urllib.error
import urllib.request
from datetime import date, timedelta
from pathlib import Path

from task_ai_app import NoRedirect, SITE_ORIGIN, SUGGEST_PATH


TOOLS = Path(__file__).resolve().parents[1] / "tools"
sys.path.insert(0, str(TOOLS / "tests"))
from _test_account import TEST_NAME, TEST_SID, assert_test_identity, test_identity_token  # noqa: E402


REFERENCE_DATE = date(2026, 11, 26)
SYNTHETIC_INPUT = {
    "text": "有两项独立任务。\n"
            "1. 明天提交实验报告。先整理实验数据，再撰写报告，最后核查结论并提交。未规定具体几点。\n"
            "2. 去图书馆领取借书证。带上预约凭条，领取后核对信息。没有规定截止日期。",
    "localDate": REFERENCE_DATE.isoformat(),
}
OPENER = urllib.request.build_opener(NoRedirect())


class CheckError(Exception):
    pass


def require(condition, message):
    if not condition:
        raise CheckError(message)


def public_publish_key():
    html = (TOOLS / "index.html").read_text(encoding="utf-8")
    match = re.search(r'var CBK\s*=\s*"([^"]+)"', html)
    require(match is not None, "网页公开配置缺少 CloudBase publish key")
    return match.group(1)


def call(payload, token=None):
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    if token:
        headers["X-Class-Token"] = token
    request = urllib.request.Request(SITE_ORIGIN + SUGGEST_PATH, method="POST", headers=headers,
                                     data=json.dumps(payload, ensure_ascii=False).encode("utf-8"))
    try:
        response = OPENER.open(request, timeout=35)
    except urllib.error.HTTPError as exc:
        response = exc
    with response:
        raw = response.read(128 * 1024 + 1)
        require(len(raw) <= 128 * 1024, "公开接口响应超出预期大小")
        require("no-store" in response.headers.get("Cache-Control", "").lower(), "公开接口缺少 no-store")
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (ValueError, RecursionError):
            raise CheckError(f"公开接口返回无效 JSON（HTTP {response.code}）") from None
        return response.code, payload


def check_drafts(payload):
    drafts = payload.get("drafts") if isinstance(payload, dict) else None
    require(isinstance(drafts, list) and len(drafts) == 2, "两项独立待办未生成两份草稿")
    for draft in drafts:
        require(isinstance(draft, dict), "草稿不是对象")
        require(all(isinstance(draft.get(field), str) for field in ("title", "notes", "due", "dueTime")),
                "草稿缺少可编辑文本字段")
        steps = draft.get("steps")
        require(isinstance(steps, list) and len(steps) <= 12
                and all(isinstance(step, dict) and isinstance(step.get("text"), str) and step["text"].strip()
                        and isinstance(step.get("note"), str) for step in steps), "草稿步骤格式异常")
        suggestions = draft.get("suggestions")
        require(isinstance(suggestions, list) and len(suggestions) <= 3
                and all(isinstance(tip, str) for tip in suggestions), "完成建议格式异常")

    report = next((draft for draft in drafts if "报告" in draft["title"]), None)
    library = next((draft for draft in drafts if re.search(r"借[书阅]证", draft["title"])), None)
    require(report is not None and library is not None and report is not library, "两项草稿标题未保留各自的目标")
    require(report["due"] == (REFERENCE_DATE + timedelta(days=1)).isoformat() and report["dueTime"] == "",
            "实验报告未正确换算明天或自行填入了钟点")
    require(len(report["steps"]) >= 2, "实验报告没有拆分出多个步骤")
    require(library["due"] == "" and library["dueTime"] == "", "借书证草稿自行填入了截止日期或钟点")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expect-disabled", action="store_true", help="require HTTP 503 ai_unavailable")
    args = parser.parse_args()
    try:
        status, payload = call({})
        require(status == 401 and payload == {"error": "unauthorized"}, f"匿名请求预期 401，实际 HTTP {status}")
        print("PASS 匿名请求返回 401")
        assert_test_identity(TEST_SID, TEST_NAME, where="task_ai_live_check")
        token = test_identity_token(SITE_ORIGIN + "/v1/rdb/rest/", public_publish_key())
        status, payload = call(SYNTHETIC_INPUT, token)
        if args.expect_disabled:
            require(status == 503 and payload == {"error": "ai_unavailable"},
                    f"测试令牌请求预期 503 ai_unavailable，实际 HTTP {status}")
            print("PASS 携带测试令牌的请求返回预期的 503 ai_unavailable")
        else:
            require(status == 200, f"真实模型联调预期 200，实际 HTTP {status}")
            check_drafts(payload)
            print("PASS 两份草稿、步骤与截止日期符合预期")
    except CheckError as exc:
        print(f"FAIL {exc}", file=sys.stderr)
        return 1
    except OSError:
        print("FAIL 公开接口请求或本机公开配置读取失败", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
