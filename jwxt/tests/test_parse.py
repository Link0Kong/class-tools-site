# -*- coding: utf-8 -*-
"""tests/test_parse.py — 课表解析器单元测试（固定 fixture，不联网）。

用法：
    python tests/test_parse.py     # 也可以 python -m pytest tests/test_parse.py
"""

import json
import os
import sys
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

import jwxt  # noqa: E402

FIXTURES = os.path.join(HERE, "fixtures")


def load(name):
    with open(os.path.join(FIXTURES, name), "r", encoding="utf-8") as f:
        return f.read()


def pick(result, name, day=None, start=None):
    for c in result["c"]:
        if (c["name"] == name and (day is None or c["day"] == day)
                and (start is None or c["start"] == start)):
            return c
    raise AssertionError("未找到课程：%s day=%s start=%s；实际=%s" % (
        name, day, start, [(c["name"], c["day"], c["start"]) for c in result["c"]]))


def assert_ascii_weeks(course):
    weeks = course["weeks"]
    assert weeks, "weeks 不能为空"
    assert "，" not in weeks and "、" not in weeks, "weeks 必须用英文逗号：%r" % weeks
    assert "周" not in weeks, "weeks 不能带「周」字：%r" % weeks


# ---------------------------------------------------------------------------
# fixture 1：经典 #kbtable + kbcontent + font[title]
# ---------------------------------------------------------------------------

def test_basic_parse():
    result = jwxt.parse_timetable(load("fixture_basic.html"), "2026-09-07")
    assert result["t"] == "2026-09-07"
    assert result["meta"]["source"] == "html"
    assert len(result["c"]) == 6, [c["name"] for c in result["c"]]

    math = pick(result, "高等数学", 0)
    assert (math["start"], math["end"]) == (1, 2)
    assert math["teacher"] == "龚志伟"
    assert math["room"] == "自强楼(教室01104)"
    assert math["weeks"] == "2-4"
    assert math["parity"] == "all"

    tue = pick(result, "高等数学", 1)
    assert (tue["start"], tue["end"]) == (1, 2)

    english = pick(result, "大学英语", 3)
    assert (english["start"], english["end"]) == (1, 2)
    assert english["weeks"] == "1-16"

    tcm = pick(result, "中医学", 0)
    assert (tcm["start"], tcm["end"]) == (3, 4)
    assert tcm["weeks"] == "2-5,7-10"

    pe = pick(result, "体育1", 4)
    assert (pe["start"], pe["end"]) == (3, 4)
    assert pe["teacher"] == "甘子怡讲师（高校）"
    assert pe["weeks"] == "2-3,5,7-10,13-18"

    prog = pick(result, "C语言程序设计", 0)
    assert (prog["start"], prog["end"]) == (7, 8)
    assert prog["room"] == "自强楼(01514-计算机实验室2)"

    for c in result["c"]:
        assert_ascii_weeks(c)
        assert 0 <= c["day"] <= 6
        assert 1 <= c["start"] <= c["end"] <= 12


# ---------------------------------------------------------------------------
# fixture 2：单双周 / 同格多课 / <hr> 分块 / rowspan 跨大节
# ---------------------------------------------------------------------------

def test_parity_and_multi_course():
    result = jwxt.parse_timetable(load("fixture_parity_multi.html"), "2026-09-07")
    names = [c["name"] for c in result["c"]]

    odd = pick(result, "体育1", 0)
    assert odd["weeks"] == "1,3,5,7,9,11,13,15", odd["weeks"]
    assert odd["parity"] == "all"

    even = pick(result, "思想道德与法治", 1)
    assert even["weeks"] == "2,4,6,8,10,12,14,16", even["weeks"]

    mil = pick(result, "军事理论", 1)
    assert mil["weeks"] == "2,5-6,8,10,14-15"

    # 同一个 td / 同一个 div（<hr> 分隔）里的多门课都要解出来
    c1 = pick(result, "C语言程序设计", 2)
    assert c1["weeks"] == "1-8"
    c2 = pick(result, "C语言程序设计实验", 2)
    assert c2["weeks"] == "9-16"
    assert c1["room"] == c2["room"] == "自强楼(01514-计算机实验室2)"

    # rowspan=2 跨两个大节 → 3-6 节
    ds = pick(result, "数据结构", 3)
    assert (ds["start"], ds["end"]) == (3, 6), (ds["start"], ds["end"])
    assert ds["weeks"] == "3-5,7-14"
    assert ds["room"] == "厚德楼(教室03205)"

    assert len(names) == len(set(names)) == 6


# ---------------------------------------------------------------------------
# fixture 3：无 id/无 kbcontent 的朴素表格 + 显式节次覆盖
# ---------------------------------------------------------------------------

def test_alt_table_and_explicit_sections():
    result = jwxt.parse_timetable(load("fixture_alt.html"), "2026-09-07")
    math = pick(result, "高等数学", 0)
    # 行内显式 (7-8节) 覆盖行标签推断
    assert (math["start"], math["end"]) == (7, 8), (math["start"], math["end"])
    assert math["weeks"] == "1-16"
    assert math["teacher"] == "王老师"
    assert math["room"] == "自强楼(教室01104)"

    english = pick(result, "大学英语", 1)
    assert (english["start"], english["end"]) == (3, 4)  # 第二个大节兜底
    assert english["teacher"] == "李梅"


# ---------------------------------------------------------------------------
# fixture 4：真实新版 qz-weeklyTable（2026-11-03 从教务系统抓取后裁剪：去 tooltip）
#
# ⚠️ 已用教务系统「有课表课程」列表（xskb_list.do?viweType=1）交叉核对：
#    高等数学=周一/周三/周五、军事理论=周二、计算机导论=周三/周四、
#    C语言=周二/周三、体育1=周一/周六、周日无课。
#    页面 thead 却是「星期日」打头（服务器模板 bug），tbody 数据列实际「周一在前」，
#    所以默认按列位置映射（col1→周一），而不是按 th 文本。
# ---------------------------------------------------------------------------

def test_qz_weekly_real_fixture():
    result = jwxt.parse_timetable(load("qz_weekly_real.html"), "2026-09-07")
    assert result["t"] == "2026-09-07"
    assert result["meta"]["parser"] == "qz-weekly"
    assert result["meta"]["term"] == "2026-2027-1"
    assert result["meta"]["count"] == len(result["c"]) == 32

    per_day = {d: sum(1 for c in result["c"] if c["day"] == d) for d in range(7)}
    assert per_day == {0: 8, 1: 8, 2: 6, 3: 6, 4: 2, 5: 2, 6: 0}, per_day

    # 高等数学：周一 1-3节{2-3} + 周一 1-2节{4} + 周三 6-8节 + 周五 1-3节
    math_mon = [c for c in result["c"] if c["name"] == "高等数学" and c["day"] == 0]
    assert len(math_mon) == 2, math_mon
    assert {(c["start"], c["end"], c["weeks"]) for c in math_mon} == {
        (1, 3, "2-3"), (1, 2, "4")}
    assert all(c["teacher"] == "龚志伟" and c["room"] == "自强楼(教室01104)"
               for c in math_mon)
    math_wed = pick(result, "高等数学", 2)
    assert (math_wed["start"], math_wed["end"]) == (6, 8)
    assert math_wed["weeks"] == "2-8,13-18"
    math_fri = pick(result, "高等数学", 4)
    assert (math_fri["start"], math_fri["end"]) == (1, 3)
    assert math_fri["weeks"] == "2-3,6-9,13-17"
    assert math_fri["room"] == "自强楼(教室01217)"

    # 军事理论：周二 3-5节，按地点拆成两条
    mil = [c for c in result["c"] if c["name"] == "军事理论"]
    assert len(mil) == 2, mil
    assert {(c["day"], c["start"], c["end"], c["room"]) for c in mil} == {
        (1, 3, 5, "厚德楼(教室02111)"), (1, 3, 5, "网络平台(网络平台)")}
    mil_classroom = [c for c in mil if c["room"] == "厚德楼(教室02111)"][0]
    assert mil_classroom["weeks"] == "2,5-6,8,10,14-15"
    mil_net = [c for c in mil if c["room"] == "网络平台(网络平台)"][0]
    assert mil_net["weeks"] == "3-4,7,9,13"

    # 计算机导论：周三 1-3节 / 周四 3-5节；C 语言：周二 1-2 / 周三 4-5
    cs = [c for c in result["c"] if c["name"] == "计算机科学导论与Python实践"]
    assert {(c["day"], c["start"], c["end"]) for c in cs} == {(2, 1, 3), (3, 3, 5)}
    clang = [c for c in result["c"] if c["name"] == "C语言程序设计"]
    assert {(c["day"], c["start"], c["end"]) for c in clang} == {(1, 1, 2), (2, 4, 5)}

    # 体育1：周一 8-9节、周六 2-5节{3}、周六 6-9节{9}
    pe = [c for c in result["c"] if c["name"] == "体育1"]
    assert {(c["day"], c["start"], c["end"]) for c in pe} == {
        (0, 8, 9), (5, 2, 5), (5, 6, 9)}
    assert per_day[6] == 0  # 周日无课

    for course in result["c"]:
        assert_ascii_weeks(course)
        assert course["parity"] == "all"
        assert 0 <= course["day"] <= 6
        assert 1 <= course["start"] <= course["end"] <= 12


def test_qz_header_order_override():
    """--day-order header 仅作调试：按 th 文本（周日打头）会把数据列整体平移一天。"""
    result = jwxt.parse_timetable(load("qz_weekly_real.html"), "2026-09-07",
                                  day_order="header")
    assert not [c for c in result["c"] if c["name"] == "高等数学" and c["day"] == 0]
    assert [c for c in result["c"] if c["name"] == "高等数学" and c["day"] == 6]


def test_list_view_cross_check():
    """独立交叉校验：教务系统「有课表课程」列表（viweType=1）带显式「周X第a-b节」，
    用它验证 qz 周表按列位置映射出来的 day/节次/周次集合完全一致。"""
    with open(os.path.join(FIXTURES, "list_view_rows.json"), "r", encoding="utf-8") as f:
        list_doc = json.load(f)

    expected = {}  # (name, day, start, end) -> weeks 并集
    for row in list_doc["rows"]:
        for segment in str(row["time"]).split(";"):
            if not segment.strip():
                continue
            for item in jwxt.parse_list_view_time(segment):
                key = (row["name"], item["day"], item["start"], item["end"])
                expected.setdefault(key, set()).update(jwxt.weeks_to_set(item["weeks"]))

    qz = jwxt.parse_timetable(load("qz_weekly_real.html"), "2026-09-07")
    actual = {}
    for course in qz["c"]:
        key = (course["name"], course["day"], course["start"], course["end"])
        actual.setdefault(key, set()).update(jwxt.weeks_to_set(course["weeks"]))

    missing_in_qz = sorted(set(expected) - set(actual))
    missing_in_list = sorted(set(actual) - set(expected))
    assert not missing_in_qz, "周表解析缺少列表里的课：%s" % (missing_in_qz,)
    assert not missing_in_list, "周表解析多出列表里没有的课：%s" % (missing_in_list,)
    for key in sorted(expected):
        assert actual[key] == expected[key], "%s 周次不一致：周表=%s 列表=%s" % (
            key, sorted(actual[key]), sorted(expected[key]))

    def days_of(items, name):
        return {k[1] for k in items if k[0] == name}

    for name in {row["name"] for row in list_doc["rows"]}:
        assert days_of(actual, name) == days_of(expected, name), name


# ---------------------------------------------------------------------------
# 纯函数
# ---------------------------------------------------------------------------

def test_compress_weeks():
    assert jwxt.compress_weeks([2, 3, 4, 6] + list(range(9, 19))) == "2-4,6,9-18"
    assert jwxt.compress_weeks([1, 3, 5]) == "1,3,5"
    assert jwxt.compress_weeks(jwxt.weeks_to_set("1-3,5-6")) == "1-3,5-6"
    assert jwxt.compress_weeks(set()) == ""


def test_weeks_to_set():
    assert jwxt.weeks_to_set("3-5,7-14(周)") == set(range(3, 6)) | set(range(7, 15))
    assert jwxt.weeks_to_set("1-16周(单)") == {1, 3, 5, 7, 9, 11, 13, 15}
    assert jwxt.weeks_to_set("1-16周(双)") == {2, 4, 6, 8, 10, 12, 14, 16}
    assert jwxt.weeks_to_set("2,5,6,8,10,14,15(周)") == {2, 5, 6, 8, 10, 14, 15}


def test_normalize_term_start():
    assert jwxt.normalize_term_start("2026-09-07") == "2026-09-07"
    assert jwxt.normalize_term_start("2026年9月7日") == "2026-09-07"
    assert jwxt.normalize_term_start("2026.9.7") == "2026-09-07"
    assert jwxt.normalize_term_start("") == ""


# ---------------------------------------------------------------------------
# 登录编码 / scode+sxh 抓取 / 发布链接
# ---------------------------------------------------------------------------

def test_login_encoding():
    scode = "".join(str((i * 7) % 10) for i in range(120))
    sxh = "1313333221313323122123112122213131213322333211321231323"
    encoded = jwxt.build_login_encoded("0000000000", "wrong-password", scode, sxh)
    code = ("%%%".join([
        jwxt.encode_inp("0000000000"),
        jwxt.encode_inp("wrong-password"),
        jwxt.encode_inp(" "),
    ]))
    # 结构约束：前 55 个字符每个后面都跟了 scode 片段；编码后长度 = 原文长度 + 消耗的 scode 长度
    used = sum(int(sxh[i]) for i in range(min(55, len(code))))
    assert len(encoded) == len(code) + used
    assert encoded.startswith(code[0])
    assert jwxt.encode_inp(" ") == base64_of(" ") == "IA=="


def base64_of(text):
    import base64
    return base64.b64encode(text.encode("utf-8")).decode("ascii")


def test_extract_scode_sxh():
    html = 'xxx var scode = "%s";\n var sxh = "%s"; yyy' % ("a" * 98, "1313333221313323122123112122213131213322333211321231323")
    got = jwxt.extract_scode_sxh(html)
    assert got is not None
    assert got[0] == "a" * 98
    assert got[1].startswith("131333")
    # 页面没带随机参数时不能瞎编
    assert jwxt.extract_scode_sxh("<html>no consts</html>") is None


def test_publish_url_roundtrip():
    courses = [{
        "name": "高等数学", "teacher": "龚志伟", "room": "自强楼(教室01104)",
        "day": 0, "start": 1, "end": 2, "weeks": "2-4", "parity": "all",
    }]
    url = jwxt.build_publish_url(courses, "2026-09-07")
    assert url.startswith("https://tool.furina.fun/#tt=")
    payload = url.split("#tt=", 1)[1]
    assert "+" not in payload and "/" not in payload and "=" not in payload
    decoded = json.loads(jwxt.b64url_decode(payload).decode("utf-8"))
    assert decoded == {"c": courses, "t": "2026-09-07"}


# ---------------------------------------------------------------------------
# app.do JSON 解析（真实课表 JSON 接口的兜底）
# ---------------------------------------------------------------------------

def test_parse_api_timetable():
    items = [
        {"kcmc": "高等数学", "jsxm": "龚志伟", "jsmc": "自强楼101",
         "kcsj": "10102", "kkzc": "1-16", "sjbz": "0"},
        {"kcmc": "体育1", "jsxm": "甘子怡", "jsmc": "篮球场",
         "kcsj": "30809", "kkzc": "1-16", "sjbz": "1"},
        {"kcmc": "军事理论", "jsxm": "沈国俊", "jsmc": "厚德楼2111",
         "kcsj": "20304", "kkzc": "2,5,6,8,10,14,15", "sjbz": "2"},
    ]
    result = jwxt.parse_api_timetable(items, "2026-09-07")
    assert result["meta"]["source"] == "app.do"
    math = pick(result, "高等数学", 0)
    assert (math["start"], math["end"]) == (1, 2)
    assert math["weeks"] == "1-16"
    pe = pick(result, "体育1", 2)
    assert (pe["start"], pe["end"]) == (8, 9)
    assert pe["weeks"] == "1,3,5,7,9,11,13,15"
    mil = pick(result, "军事理论", 1)
    assert (mil["start"], mil["end"]) == (3, 4)
    # sjbz=2 → 双周，{2,5,6,8,10,14,15} 过滤后 {2,6,8,10,14}
    assert mil["weeks"] == "2,6,8,10,14"


# ---------------------------------------------------------------------------

def main():
    tests = [(name, fn) for name, fn in sorted(globals().items())
             if name.startswith("test_") and callable(fn)]
    failed = 0
    for name, fn in tests:
        try:
            fn()
            print("PASS  %s" % name)
        except Exception:
            failed += 1
            print("FAIL  %s" % name)
            traceback.print_exc()
    print("\n%d/%d passed" % (len(tests) - failed, len(tests)))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
