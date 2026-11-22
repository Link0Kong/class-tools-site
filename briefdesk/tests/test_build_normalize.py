# -*- coding: utf-8 -*-
"""builder 数据侧单测：时间归一（契约 §1/§4）+ 发送者身份映射（契约 §5）。

运行：
  C:\\briefdesk\\venv\\Scripts\\python.exe G:\\ClassTools\\web\\briefdesk\\tests\\test_build_normalize.py

只读产品数据（class-*.json / notice-manual-patches.json / ai-triage-notices.json），
临时文件写在 tests 目录内并清理。
"""
import json
import os
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

BASE = Path(r"G:\ClassTools\web\briefdesk")
sys.path.insert(0, str(BASE))
sys.path.append(r"C:\briefdesk\scripts")

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import build_notice_board as bnb  # noqa: E402

PASS = 0
FAIL = 0
FAILED = []


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("PASS " + name)
    else:
        FAIL += 1
        FAILED.append(name)
        print("FAIL " + name + ("  " + str(detail) if detail else ""))


def eq(name, actual, expected):
    check(name, actual == expected, "expected=%r actual=%r" % (expected, actual))


# ---------------------------------------------------------------- 1. 身份映射（契约 §5）
print("---- §5 发送者身份映射（网名 → 姓名 + 职务）----")
roster = bnb.load_roster()
check("roster 非空", bool(roster.get("by_clean")))
info = bnb._roster_lookup("网名B", roster)
eq("网名B → 姓名", (info or {}).get("name"), "同学B")
eq("网名B → 职务", (info or {}).get("role"), "学习委员")
eq("网名B → 班委徽标", (info or {}).get("badge"), "班委")
eq("08同学C → 姓名", (bnb._roster_lookup("08同学C", roster) or {}).get("name"), "同学C")
eq("64同学A → 姓名", (bnb._roster_lookup("64同学A", roster) or {}).get("name"), "同学A")
check("未知发送者不误命中", bnb._roster_lookup("路过的陌生人", roster) is None)

it = {"kind": "file", "time": "10-29 15:27", "from": "网名B", "name": "花名册.xls"}
bnb._fill_sender(it, roster)
eq("_fill_sender fromName", it.get("fromName"), "同学B")
eq("_fill_sender fromRole", it.get("fromRole"), "学习委员")
eq("_fill_sender fromBadge", it.get("fromBadge"), "班委")
eq("_fill_sender 保留 fromRaw", it.get("fromRaw"), "网名B")

g_file = {"id": "g_qqfile_1a81286a3a", "cat": "班级事务", "title": "更新版学生花名册发布",
          "items": [{"kind": "file", "label": "附件", "time": "10-29 15:27",
                     "from": "网名B", "name": "级信息管理与信息系统-花名册学生名单.xls"}]}
bnb.attach_sender_roles([g_file])
eq("A5 花名册卡 senderName", g_file.get("senderName"), "同学B")
eq("A5 花名册卡 senderRole", g_file.get("senderRole"), "学习委员")
check("A5 不再以网名B作为发送者", "网名B" not in json.dumps(
    {k: v for k, v in g_file.items() if k != "items"}, ensure_ascii=False))

# ---------------------------------------------------------------- 2. 人工补丁字段（契约 §1）
print("---- §1 人工补丁 GROUP_PATCH_FIELDS / ISO 校验 ----")
for k in ("deadlineAction", "eventAction", "signupStart", "signupEnd"):
    check("GROUP_PATCH_FIELDS 含 " + k, k in bnb.GROUP_PATCH_FIELDS)
gp = {"id": "g_patch"}
bnb._apply_patch_to_group(gp, {"signupStart": "2026-11-08T14:00", "signupEnd": "2026-11-08T18:00",
                               "deadlineAction": "报名截止"})
eq("补丁 signupStart 补 +08:00", gp.get("signupStart"), "2026-11-08T14:00:00+08:00")
eq("补丁 signupEnd 补 +08:00", gp.get("signupEnd"), "2026-11-08T18:00:00+08:00")
eq("补丁 deadlineAction", gp.get("deadlineAction"), "报名截止")

# ---------------------------------------------------------------- 3. 时间归一（契约 §4）
print("---- §4 时间归一（notice_time + builder 补缺）----")

# 3.1 手抄报：报名优先（signup 11-03 12:00–20:30；作品 deadline 11-12 20:00 保留）
g_food = {
    "id": "g_food", "cat": "活动", "title": "惜粮手抄报活动通知",
    "deadline": "2026-11-12T20:00:00+08:00",
    "items": [{"kind": "text", "label": "活动通知", "time": "11-02 10:46", "from": "21同学I",
               "text": "各位同学大家好～这个秋日，由福建中医药大学学生膳食管理委员会承办的“食不易得，惜粮在行”"
                       "主题活动正式启动啦！活动对象：全体在校学生。活动时间：2026年10月30日-11月15日。"
                       "开群时间：11月3日 12:00。收集表报名时间：11月3日12:00-20:30。参与者在 11月5日-11日期间"
                       "完成主题手抄报绘画，于 11月12日20:00 前将作品拍照提交至群作业，并在作品右下角写上"
                       "姓名、学号、学院信息，审核合格后可获得活动证明。具体内容见策划书。"},
              {"kind": "form", "label": "活动报名", "time": "11-02 10:46", "name": "报名表"}],
}
bnb.MANUAL_SET_FIELDS.clear()
bnb.normalize_group_times([g_food])
eq("A4 手抄报 signupStart", g_food.get("signupStart"), "2026-11-03T12:00:00+08:00")
eq("A4 手抄报 signupEnd", g_food.get("signupEnd"), "2026-11-03T20:30:00+08:00")
check("A4 手抄报 deadline 保留作品提交", str(g_food.get("deadline") or "").startswith("2026-11-12"),
      g_food.get("deadline"))
eq("A4 手抄报 deadlineAction", g_food.get("deadlineAction"), "投稿截止")

# 3.2 药膳：人工补丁追加更正文本后 final pass 刷新 signup 到 11-07（人工字段优先）
g_food2 = {
    "id": "g_qqm_7704134971497063025_c0", "cat": "活动", "title": "药膳答题打卡活动报名",
    "items": [{"kind": "text", "label": "通知", "time": "11-04 10:18", "from": "21同学I",
               "text": "线上活动QQ群：1127693680 2026年11月7日—11月14日 2026年11月5日12:00—18:00 "
                       "11月5日12:00开放“食养本草，润愈身心”药膳知识线上答题打卡QQ活动群，"
                       "填写群精华消息内的线上报名表并核对信息正确即为报名成功。"}],
}
bnb.MANUAL_SET_FIELDS.clear()
bnb.normalize_group_times([g_food2])
bnb.apply_manual_patches([g_food2])
bnb.normalize_group_times([g_food2], final=True)
eq("A3 药膳 deadline=人工补丁 11-07 18:00", g_food2.get("deadline"), "2026-11-07T18:00:00+08:00")
eq("A3 药膳 eventAt=人工补丁 11-07 12:00", g_food2.get("eventAt"), "2026-11-07T12:00:00+08:00")
eq("A3 药膳 signupStart=更正 11-07 12:00", g_food2.get("signupStart"), "2026-11-07T12:00:00+08:00")
eq("A3 药膳 signupEnd=更正 11-07 18:00", g_food2.get("signupEnd"), "2026-11-07T18:00:00+08:00")
check("A3 药膳 deadlineAction 含「截止」", "截止" in str(g_food2.get("deadlineAction") or ""),
      g_food2.get("deadlineAction"))
bnb.MANUAL_SET_FIELDS.clear()

# 3.2b 药膳 c1（回归）：正文含「进群修改群昵称」不是更正来源，final pass 不得刷新 signup
#     （曾把「活动周期 11月7日—11月14日」误当报名 end，覆盖成 11-14）
g_c1 = {
    "id": "g_qqm_7704134971497063025_c1", "cat": "活动", "title": "药膳手记线上打卡活动报名",
    "items": [{"kind": "text", "label": "通知", "time": "11-04 10:18", "from": "21同学I",
               "text": "拾味本草，手记食养”药膳手记线上打卡活动。线上活动QQ群：817436248。"
                       "活动周期内（11月7日至11月14日）需完成共计5次有效打卡，结束后将全部打卡照片统一提交至群作业。"
                       "2026年11月5日12:00—18:00 2026年11月5日12:00开放报名QQ群聊：817436248"
                       "（活动群聊上限200人，名额满后关闭群聊），进群修改群昵称为“学院+姓名+学号”，"
                       "填写群精华消息内报名表并核对信息正确即为报名成功。"}],
}
bnb.normalize_group_times([g_c1])
eq("c1 non-final signupStart=11-05 12:00", g_c1.get("signupStart"), "2026-11-05T12:00:00+08:00")
eq("c1 non-final signupEnd=11-05 18:00", g_c1.get("signupEnd"), "2026-11-05T18:00:00+08:00")
check("c1 不误判为补充/更正卡", not bnb._has_supplement_item(g_c1))
bnb.normalize_group_times([g_c1], final=True)
eq("c1 final 不刷新 signupStart", g_c1.get("signupStart"), "2026-11-05T12:00:00+08:00")
eq("c1 final 不刷新 signupEnd（不得变成 11-14）", g_c1.get("signupEnd"), "2026-11-05T18:00:00+08:00")

# 3.3 申报材料：deadline 11-06 12:00 不被文本重解析覆盖，动作=报送姓名截止
g_apply = {
    "id": "g_ait_5396a55f24", "cat": "班级事务", "title": "申报材料报送提醒",
    "deadline": "2026-11-06T12:00:00+08:00", "aiTriage": True,
    "items": [{"kind": "text", "label": "通知", "time": "11-05 20:47", "from": "同学A",
               "text": "请申报的同学明天中午前报送姓名，周日晚点名时需要提交材料！"}],
}
bnb.normalize_group_times([g_apply])
eq("A2 申报材料 deadline 保持 11-06 12:00", g_apply.get("deadline"), "2026-11-06T12:00:00+08:00")
eq("A2 申报材料 deadlineAction（§0.2 短词）", g_apply.get("deadlineAction"), "报送截止")
eq("A2 申报材料 eventAt 周日晚点名 19:00", g_apply.get("eventAt"), "2026-11-08T19:00:00+08:00")
eq("A2 申报材料 eventAction（§0.2 短词）", g_apply.get("eventAction"), "点名")

# 3.4 骨伤作品征集：只有 signupStart，不合成 signupEnd（显示回落 deadline）
g_gu = {
    "id": "g_qqm_7704510965381867825_c0", "cat": "活动", "title": "骨伤学院运动会作品征集",
    "deadline": "2026-11-08T00:00:00+08:00",
    "items": [{"kind": "text", "label": "通知", "time": "11-04 10:00",
               "text": "“追风逐浪，定格荣光”运动会系列征集活动。2⃣子活动二【运动风采合影征集】"
                       "11 月 5 日 12:00 开放QQ群聊，进群后填写收集表（上限 200 份）。"
                       "11 月 7 日 24:00 前提交原图照片 + 带互动的发布截图，审核通过即可获得活动证明。"}],
}
bnb.normalize_group_times([g_gu])
eq("骨伤 signupStart=11-05 12:00", g_gu.get("signupStart"), "2026-11-05T12:00:00+08:00")
check("骨伤 signupEnd 不合成（None/空）", not g_gu.get("signupEnd"), g_gu.get("signupEnd"))
eq("骨伤 deadline 保持 11-08", g_gu.get("deadline"), "2026-11-08T00:00:00+08:00")

# 3.5 征文（活动+投稿，无报名语义）：不被合成 signup，动作=投稿截止
g_essay = {
    "id": "g_essay", "cat": "活动", "title": "杏林故事征文通知",
    "deadline": "2026-11-15T23:59:00+08:00",
    "items": [{"kind": "text", "label": "原始通知", "time": "10-29 12:17", "from": "64同学A",
               "text": "关于开展“岐黄薪火·我的杏林故事”征文的通知：须为原创首发，仅接收 Word 文档。"
                       "活动截止时间：2026 年 11 月 15 日。投稿方式：作品电子版发送至邮箱 2006002@fjtcm.edu.cn。"}],
}
bnb.normalize_group_times([g_essay])
check("征文不合成 signup", not g_essay.get("signupStart") and not g_essay.get("signupEnd"),
      (g_essay.get("signupStart"), g_essay.get("signupEnd")))
eq("征文 deadlineAction=投稿截止", g_essay.get("deadlineAction"), "投稿截止")
eq("征文 deadline 保持 11-15", g_essay.get("deadline"), "2026-11-15T23:59:00+08:00")

# 3.6 运动会观众：有报名语义（征集）→ signupEnd 取 deadline（报名截止）
g_view = {
    "id": "g_games_viewer", "cat": "活动", "title": "校运动会观众征集",
    "deadline": "2026-11-03T18:30:00+08:00",
    "items": [{"kind": "text", "label": "原始通知", "time": "11-03 14:03", "from": "64同学A",
               "text": "为保证校运动会顺利开展，需要向 25 级、26 级各班征集运动会观众，每半日需要各班 6 名观众。截止今天六点半！"}],
}
bnb.normalize_group_times([g_view])
eq("观众征集 signupEnd=deadline（报名截止）", g_view.get("signupEnd"), "2026-11-03T18:30:00+08:00")
check("观众征集 deadlineAction=报名截止", "报名" in str(g_view.get("deadlineAction") or ""),
      g_view.get("deadlineAction"))

# ---------------------------------------------------------------- 3.7 第三轮 §0：legacy 卡时间/动作补全
print("---- §0.2/§0.5 动作精简 + legacy 微信卡 eventAt + 00:00 修正 ----")
eq("_short_action 报送姓名截止→报送截止", bnb._short_action("报送姓名截止"), "报送截止")
eq("_short_action 集合点名→点名", bnb._short_action("集合点名"), "点名")
eq("_short_action 活动开始→开始", bnb._short_action("活动开始"), "开始")
eq("_short_action 签到签退→签到", bnb._short_action("签到签退"), "签到")
eq("_short_action 比赛开始→比赛", bnb._short_action("比赛开始"), "比赛")
eq("_short_action 截断 >6 字", bnb._short_action("超长动作描述超过六字"), "超长动作描述"[:6])

# R1：legacy 微信卡正文只有「下午」，要补出 eventAt=11-05 14:00（用 notice_time 单一真源）
g_wx = {
    "id": "g_wxg_c66a85ae46", "cat": "活动", "title": "下午招聘会请准时到场",
    "group": "26信管班群", "source": "微信群 · 26信管班群",
    "items": [{"kind": "text", "label": "群通知", "time": "11-05 13:00",
               "text": "下午的招聘会请各班同学准时到场"}],
}
bnb.normalize_group_times([g_wx])
eq("R1 legacy 微信卡 eventAt=11-05 14:00", g_wx.get("eventAt"), "2026-11-05T14:00:00+08:00")
check("R1 legacy 微信卡 eventAction 非空且≤6 字", 0 < len(str(g_wx.get("eventAction") or "")) <= 6,
      g_wx.get("eventAction"))

# R5：OCR 赛程表 00:00 的 eventAt 用文本首个钟点（9:10）+ 5号 修正
g_ocr = {
    "id": "g_qqimg_6d052014c3", "cat": "活动", "title": "运动会项目及参赛人员安排",
    "summary": "公布运动会各项比赛时间及参赛人员名单。",
    "aiSummary": "公布运动会各项比赛时间及参赛人员名单。",
    "eventAt": "2026-11-05T00:00:00+08:00",
    "items": [{"kind": "text", "label": "名单", "time": "11-04 19:49",
               "text": "日期 项目 时间 姓名 教工女子青年组200 米 9:10 陈江美 学生女子组200米-预赛 9:40 "
                       "5号上午 杨欢欢 学生女子组标枪-预决赛 00:6 丘嘉欣"}],
}
bnb.normalize_group_times([g_ocr])
ev = str(g_ocr.get("eventAt") or "")
check("R5 00:00 eventAt 修正为文本钟点 9:10", ev.endswith("T09:10:00+08:00") or ev.endswith("T09:10"),
      ev)

# R7：长期安排 action 不被误改，recurrence 保留
g_dorm = {
    "id": "g_dorm", "cat": "班级事务", "title": "宿舍卫生检查安排",
    "recurrence": {"freq": "monthly_weeks", "weekday": 3, "weeks": [1, 2, 3],
                   "time": "17:30", "startAt": "2026-11-04T17:30:00+08:00",
                   "label": "每月前三周 周三 17:30"},
    "items": [{"kind": "text", "label": "通知", "time": "11-03 09:13",
               "text": "自本周（11.4）起，每月前三周的周三下午 5:30 例行检查。"}],
}
bnb.normalize_group_times([g_dorm])
check("R7 长期安排 recurrence 保留", (g_dorm.get("recurrence") or {}).get("freq") == "monthly_weeks",
      g_dorm.get("recurrence"))

# ---------------------------------------------------------------- 4. ai-triage 新字段透传
print("---- §1 load_ai_triage_notices 新字段透传 ----")
fd, tmp_name = tempfile.mkstemp(prefix="triage_", suffix=".json", dir=str(Path(__file__).parent))
os.close(fd)
tmp = Path(tmp_name)
try:
    tmp.write_text(json.dumps({"items": [{
        "id": "g_ait_test", "cat": "活动", "title": "药膳报名测试",
        "summary": "报名 11-07 12:00—18:00",
        "deadline": "2026-11-07T18:00", "eventAt": None,
        "deadlineAction": "报名截止", "eventAction": "活动开始",
        "signupStart": "2026-11-07T12:00", "signupEnd": "2026-11-07T18:00",
        "aiMerged": True, "supplement": True, "updatedAt": "2026-11-05T21:07:00+08:00",
        "items": [{"kind": "text", "label": "通知", "time": "11-05 12:37",
                   "text": "报名时间：2026年11月7日12:00—18:00"}],
    }]}, ensure_ascii=False), encoding="utf-8")
    old = bnb.AI_TRIAGE
    bnb.AI_TRIAGE = tmp
    try:
        items = bnb.load_ai_triage_notices()
    finally:
        bnb.AI_TRIAGE = old
    got = items[0] if items else {}
    eq("ai-triage deadlineAction 透传", got.get("deadlineAction"), "报名截止")
    eq("ai-triage eventAction 透传", got.get("eventAction"), "活动开始")
    eq("ai-triage signupStart 补 +08:00", got.get("signupStart"), "2026-11-07T12:00:00+08:00")
    eq("ai-triage signupEnd 补 +08:00", got.get("signupEnd"), "2026-11-07T18:00:00+08:00")
    eq("ai-triage deadline 补 +08:00", got.get("deadline"), "2026-11-07T18:00:00+08:00")
    check("ai-triage aiMerged 透传", got.get("aiMerged") is True, got.get("aiMerged"))
    check("ai-triage supplement 透传", got.get("supplement") is True, got.get("supplement"))
    eq("ai-triage updatedAt 透传（已更新徽标）", got.get("updatedAt"), "2026-11-05T21:07:00+08:00")
finally:
    try:
        tmp.unlink()
    except OSError:
        pass

# ---------------------------------------------------------------- 5. 合成 signup 清理（投稿类）
print("---- _drop_synthetic_signup：投稿/征文类合成 signup 清除 ----")
g_syn = {"id": "x", "cat": "活动", "deadline": "2026-11-15T23:59:00+08:00",
         "signupEnd": "2026-11-15T23:59:00+08:00",
         "items": [{"kind": "text", "time": "10-29", "text": "征文投稿截止 11 月 15 日"}]}
bnb._drop_synthetic_signup(g_syn)
check("无报名语义时清掉合成 signup", not g_syn.get("signupEnd"), g_syn.get("signupEnd"))
g_syn2 = {"id": "y", "cat": "活动", "deadline": "2026-11-03T18:30:00+08:00",
          "signupEnd": "2026-11-03T18:30:00+08:00",
          "items": [{"kind": "text", "time": "11-03", "text": "征集运动会观众，截止今天六点半"}]}
bnb._drop_synthetic_signup(g_syn2)
eq("有报名/征集语义时保留 signup", g_syn2.get("signupEnd"), "2026-11-03T18:30:00+08:00")

# ---------------------------------------------------------------- 6. 限期活动 × 长期安排（慢跑打卡回归）
# 用户 2026-11-21 反馈：冬季傍晚慢跑打卡活动（活动期 11-16 至 11-27，每日 17:00-20:00）被 AI 判成
# 每日 recurrence，整张活动卡进了「长期通知」。限期活动（正文写死起止日期 + 活动语义）必须落地成
# 一次性活动：eventAt=活动期首日 17:00、expireAt=末日 20:00；真长期安排（无活动起止日期）不受影响。
print("---- §3.8 限期活动不得当长期安排（慢跑打卡回归）----")
g_jog = {
    "id": "g_jog", "cat": "文体", "title": "冬季傍晚慢跑打卡活动", "actionable": False,
    "recurrence": {"freq": "daily", "time": "17:00", "startAt": "2026-11-19T17:00:00+08:00",
                   "until": "2026-11-27", "label": "每日17:00-20:00"},
    "items": [{"kind": "text", "label": "通知", "time": "11-17 10:54",
               "text": "“顺时冬藏·慢跑养生”冬季傍晚慢跑打卡活动来啦！福建中医药大学全体学生 "
                       "2026年11月16日至11月27日，每日17：00-20：00 旗山校区、屏山校区；"
                       "日常打卡（2026年11月19日-11月27日，每日17：00-20：00）。"}],
}
bnb.MANUAL_SET_FIELDS.clear()
bnb.resolve_recurrence_conflicts([g_jog])
check("慢跑 限期活动 recurrence 已移除", not g_jog.get("recurrence"), g_jog.get("recurrence"))
eq("慢跑 eventAt=活动期首日 17:00", g_jog.get("eventAt"), "2026-11-16T17:00:00+08:00")
eq("慢跑 expireAt=活动期末日 20:00", g_jog.get("expireAt"), "2026-11-27T20:00:00+08:00")
check("慢跑 actionable 恢复可处理", g_jog.get("actionable") is True, g_jog.get("actionable"))

# 反向：只有周期表述、没有活动起止日期的真长期安排保持不变
g_leave = {
    "id": "g_leave", "cat": "班级事务", "title": "军训期间每日请假", "actionable": False,
    "recurrence": {"freq": "daily", "time": "07:30", "startAt": "2026-11-14T07:30:00+08:00",
                   "until": "2026-11-22", "label": "每日 07:30"},
    "items": [{"kind": "text", "label": "通知", "time": "11-14 08:00",
               "text": "军训 11月14日至11月22日，每天 7:30 前把请假条私发导员。"}],
}
bnb.resolve_recurrence_conflicts([g_leave])
check("请假类（办事/报备）保留 recurrence", (g_leave.get("recurrence") or {}).get("freq") == "daily",
      g_leave.get("recurrence"))

g_dorm2 = {
    "id": "g_dorm2", "cat": "班级事务", "title": "宿舍卫生检查安排",
    "recurrence": {"freq": "monthly_weeks", "weekday": 3, "weeks": [1, 2, 3], "time": "17:30",
                   "startAt": "2026-11-04T17:30:00+08:00", "label": "每月前三周 周三 17:30"},
    "items": [{"kind": "text", "label": "通知", "time": "11-03 09:13",
               "text": "自本周（11.4）起，每月前三周的周三下午 5:30 例行检查宿舍卫生。"}],
}
bnb.resolve_recurrence_conflicts([g_dorm2])
check("每月卫生检查保留 recurrence", (g_dorm2.get("recurrence") or {}).get("freq") == "monthly_weeks",
      g_dorm2.get("recurrence"))

# ---------------------------------------------------------------- 7. 人工补丁：报名开始 + 报满即止（不臆造截止）
# 策划书原文只写「报名时间：2026年11月16日17:00」「报满即止」：signupStart=11-16 17:00，
# signupEnd/deadline 必须为空（用户 2026-11-21 明确：不虚构报名截止时间）。
print("---- §3.9 人工补丁 null=删除（报名开始保留、截止不臆造）----")
g_jog_patch = {
    "id": "g_qqm_7708988868871074939_c0", "cat": "文体", "title": "冬季傍晚慢跑打卡活动报名",
    "actionable": True, "deadline": "2026-11-17T17:00:00+08:00", "deadlineAction": "报名截止",
    "signupStart": "2026-11-17T17:00:00+08:00", "signupEnd": "2026-11-17T17:00:00+08:00",
    "eventAt": "2026-11-17T17:00:00+08:00", "eventAction": "开始",
    "recurrence": {"freq": "daily", "time": "17:00", "until": "2026-11-27", "label": "每日17:00-20:00"},
    "items": [{"kind": "text", "label": "通知", "time": "11-17 10:54",
               "text": "屏山校区慢跑打卡活动此前开放报名后仍有剩余名额，现定于今天（11月17日）下午 5:00 "
                       "重新开放报名，报满即止。"}],
}
bnb.MANUAL_SET_FIELDS.clear()
bnb.apply_manual_patches([g_jog_patch])
bnb.normalize_group_times([g_jog_patch], final=True)
bnb.resolve_recurrence_conflicts([g_jog_patch])
eq("补丁 signupStart=报名开始 11-16 17:00", g_jog_patch.get("signupStart"),
   "2026-11-16T17:00:00+08:00")
check("补丁 signupEnd=null 删除（报满即止不写截止）", not g_jog_patch.get("signupEnd"),
      g_jog_patch.get("signupEnd"))
check("补丁 deadline=null 删除", not g_jog_patch.get("deadline"), g_jog_patch.get("deadline"))
check("补丁 deadlineAction=null 删除", not g_jog_patch.get("deadlineAction"),
      g_jog_patch.get("deadlineAction"))
check("补丁 recurrence=null 删除", not g_jog_patch.get("recurrence"), g_jog_patch.get("recurrence"))
eq("补丁 eventAt=11-16 17:00", g_jog_patch.get("eventAt"), "2026-11-16T17:00:00+08:00")
eq("补丁 eventAction=报名开始", g_jog_patch.get("eventAction"), "报名开始")
eq("补丁 expireAt=活动期末 11-27 20:00", g_jog_patch.get("expireAt"), "2026-11-27T20:00:00+08:00")
check("补丁 actionable=true", g_jog_patch.get("actionable") is True)
bnb.MANUAL_SET_FIELDS.clear()

# ---------------------------------------------------------------- 7. 同一活动的聚类合并（慢跑打卡拆卡回归）
# 用户 2026-11-21 反馈：同一条合并转发记录里，「活动介绍全文」与「报名/补报名 + 策划书」被拆成两张卡，
# 介绍卡没有报名信息、随后被判成每日长期安排。同一活动（标题同主题）的聚类必须合成一张卡。
print("---- §3.10 同一活动的聚类合并（介绍 + 报名/附件）----")
clusters_in = [
    {"title": "冬季慢跑打卡活动报名", "summary": "屏山11-17 17:00重新开放报名。",
     "points": ["17:00重新开放报名"], "indexes": [0, 2]},
    {"title": "冬季慢跑打卡活动介绍", "summary": "11-16至27日两校区开展。",
     "points": ["时间11月16日至27日"], "indexes": [1]},
    {"title": "小雪主题系列活动报名", "summary": "报名11-18 12:00开始。",
     "points": ["11-18报名"], "indexes": [3]},
]
merged_clusters = bnb._merge_similar_clusters(clusters_in)
eq("同主题聚类合并成 2 组", len(merged_clusters), 2)
eq("介绍并入报名卡（indexes 并集、保持原顺序）", merged_clusters[0].get("indexes"), [0, 1, 2])
check("合并保留首个聚类的标题", merged_clusters[0].get("title") == "冬季慢跑打卡活动报名",
      merged_clusters[0].get("title"))
check("不同主题（小雪）不被误合并",
      any(c.get("title") == "小雪主题系列活动报名" for c in merged_clusters), merged_clusters)
eq("_merge_similar_clusters 幂等", bnb._merge_similar_clusters(merged_clusters), merged_clusters)
# 子活动一/二/三 这类短公共前缀不得合并
subs = [{"title": "子活动一：线下闯关八段锦", "indexes": [0]},
        {"title": "子活动二：线上手账征集", "indexes": [1]},
        {"title": "子活动三：诵读打卡", "indexes": [2]}]
eq("子活动一/二/三 不合并", len(bnb._merge_similar_clusters(subs)), 3)

# ---------------------------------------------------------------- 8. 「报名成功后进群/锁群」补充片段（2026-11-22）
# 用户反馈：「11月22日（今天） 12:00 前进打卡群」上下文不对——补充消息被拆成独立卡，二维码又挂在
# 活动卡上。同记录里唯一活动主体聚类时，补充片段必须并回活动卡（条目记为「补充通知」）。
print("---- §3.11 报名成功后进群/锁群补充片段并回活动卡 ----")
_msgs = [
    {"kind": "file", "name": "“翰墨腾龙韵”系列主题活动策划书.pdf"},
    {"kind": "text", "text": "活动时间：2026年11月22日—11月25日；活动对象：全体学生；"
                             "报名方式：11月21日18:00-22:00在服务号报名；报名成功后加入QQ活动群。"},
    {"kind": "text", "text": "成功报名的同学加入对应的二维码，在11月22日12点之前进群，到点即锁群"},
    {"kind": "image", "name": "qr1.jpg"},
]
_clusters = [
    {"title": "龙狮系列主题活动总览", "summary": "", "points": [], "indexes": [0, 1, 3]},
    {"title": "书法打卡报名进群", "summary": "", "points": ["到点即锁群"], "indexes": [2]},
]
new_clusters, supp = bnb._merge_supplement_clusters(_clusters, _msgs)
eq("补充片段并入主活动卡（indexes 并集）", [c.get("indexes") for c in new_clusters], [[0, 1, 2, 3]])
eq("补充片段消息序号", supp, {2})
check("并入的要点保留「到点即锁群」",
      any("锁群" in p for p in new_clusters[0].get("points") or []), new_clusters[0].get("points"))
# 反向 1：同记录里有两个活动主体聚类 → 不猜，原样返回
_msgs2 = _msgs + [{"kind": "text", "text": "活动时间：12月1日—12月30日；报名方式：扫码进群。"}]
_clusters2 = [
    {"title": "活动A", "indexes": [0, 1]},
    {"title": "活动B", "indexes": [4]},
    {"title": "进群", "indexes": [2]},
]
kept2, supp2 = bnb._merge_supplement_clusters(_clusters2, _msgs2)
eq("多个活动主体聚类时不合并", len(kept2), 3)
eq("多个活动主体聚类时无补充序号", supp2, set())
# 反向 2：自己就带活动主体信息（活动时间/报名方式）的聚类不是补充片段
_clusters3 = [
    {"title": "活动A", "indexes": [0, 1]},
    {"title": "活动C", "indexes": [5]},
]
_msgs3 = _msgs + [{"kind": "text", "text": "活动时间：12月5日；报名方式：扫码进群，11月22日前进群。"}]
kept3, supp3 = bnb._merge_supplement_clusters(_clusters3, _msgs3)
eq("带活动主体信息的聚类不并入", len(kept3), 2)
eq("带活动主体信息的聚类无补充序号", supp3, set())

# ---------------------------------------------------------------- 9. 报名截止已过、但还有更晚截止（2026-11-22）
# 用户反馈：龙狮书法打卡报名 11-21 22:00 截止后整卡被判已截止，活动 11-22 才开始、11-25 还要交作品；
# 报名截止已过但有更晚提交截止时，去掉已过的 signupEnd，卡片跟踪剩下的截止（不要整卡提前过期）。
print("---- §3.12 报名截止后仍跟踪更晚的提交截止 ----")
_now = datetime.now()
_past = (_now - timedelta(hours=3)).strftime("%Y-%m-%dT%H:%M:%S+08:00")
_future = (_now + timedelta(days=3)).strftime("%Y-%m-%dT%H:%M:%S+08:00")
g_act = {"id": "g_act", "title": "龙狮系列主题活动", "actionable": True,
         "signupStart": (_now - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%S+08:00"),
         "signupEnd": _past, "deadline": _future,
         "eventAt": (_now - timedelta(hours=8)).strftime("%Y-%m-%dT%H:%M:%S+08:00")}
bnb._drop_passed_signup_end([g_act])
check("有更晚截止：去掉已过的 signupEnd", not g_act.get("signupEnd"), g_act.get("signupEnd"))
eq("expireAt 不早于该截止", g_act.get("expireAt"), g_act.get("deadline"))
check("报名开始保留", bool(g_act.get("signupStart")), g_act.get("signupStart"))
# 反向 1：没有更晚截止（讲座/比赛这种报名截止后就没事了）→ 保留 signupEnd，按契约进已截止
g_closed = {"id": "g_closed", "title": "讲座报名", "signupEnd": _past,
            "deadline": (_now - timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%S+08:00")}
bnb._drop_passed_signup_end([g_closed])
eq("没有更晚截止：保留 signupEnd", g_closed.get("signupEnd"), _past)
# 反向 2：多报名窗口（signupWindows）不动
g_win = {"id": "g_win", "title": "多窗口活动", "signupEnd": _past, "deadline": _future,
         "signupWindows": [{"label": "子活动一", "end": _past}]}
bnb._drop_passed_signup_end([g_win])
eq("多报名窗口保留 signupEnd", g_win.get("signupEnd"), _past)

# ---------------------------------------------------------------- 10. 组队/分组事项归并（2026-11-23）
# 用户反馈：「穴位打卡寻宝分组及组名报送识别错误，分组是军事理论的分组」。组队 / 随机分组 / 组名报送
# 是同一条线；活动宣发名（穴位打卡寻宝 / 识艾护己）只是上下文碎片，不得挂到分组卡上。
print("---- §3.13 组队/分组碎片卡并回军事理论组队卡 ----")
g_team = {
    "id": "g_team", "cat": "班级事务", "title": "军事理论课组队报送",
    "source": "QQ 群 · 2026级信息管理与信息系统",
    "deadline": "2026-11-22T23:59:00+08:00", "deadlineAction": "报送截止",
    "items": [{"kind": "text", "label": "通知", "time": "11-19 20:42",
               "text": "请各位同学在11.22号(周日)内把军事理论的组队发我，每队6人"},
              {"kind": "text", "label": "补充通知", "time": "11-22 12:00", "supplement": True,
               "text": "军事理论小组名单请尽快交给我包括组名，晚自习后没有的组队的同学将随机分组"}],
}
g_grp = {
    "id": "g_grp", "cat": "活动", "title": "穴位打卡寻宝分组及组名报送",
    "source": "QQ 群 · 2026级信息管理与信息系统聊天群",
    "deadline": "2026-11-23T12:00:00+08:00", "deadlineAction": "报送截止",
    "items": [{"kind": "text", "label": "通知", "time": "11-22 23:32", "text": "穴位打卡寻宝"},
              {"kind": "text", "label": "通知", "time": "11-22 23:32", "text": "识艾护己，闯关同行"},
              {"kind": "text", "label": "通知", "time": "11-22 23:42", "text": "[image]"},
              {"kind": "text", "label": "通知", "time": "11-22 23:43",
               "text": "@11刘迎姿 @18张培鑫 @20刘妍妍 @54陈思平 @55曾婷慧 @22程韩 一组"},
              {"kind": "text", "label": "通知", "time": "11-22 23:47",
               "text": "分组结果已出，请各组明天中午12点前把组名给学委"}],
}
g_activity = {
    "id": "g_activity", "cat": "活动", "title": "11-29 穴位打卡定向越野",
    "source": "QQ 群 · 2026级信息管理与信息系统聊天群",
    "eventAt": "2026-11-29T09:00:00+08:00", "signupStart": "2026-11-24T12:00:00+08:00",
    "items": [{"kind": "text", "label": "通知", "time": "11-22 23:32",
               "text": "穴位打卡寻宝定向越野，活动对象：全体学生，活动时间：11月29日，报名方式：服务号报名，每校5人组队参赛"}],
}
merged_groups = bnb.merge_grouping_notices([g_team, g_grp, g_activity])
ids = [g.get("id") for g in merged_groups]
check("分组碎片卡并入军事理论组队卡", "g_grp" not in ids and "g_team" in ids, ids)
eq("活动卡不参与（保留）", "g_activity" in ids, True)
target = next(g for g in merged_groups if g.get("id") == "g_team")
check("后发卡并入组队卡（含 @名单条目）",
      any("@" in str(it.get("text") or "") for it in target.get("items") or []),
      [it.get("text") for it in target.get("items") or []][:3])
check("活动名碎片（穴位打卡寻宝/识艾护己/[image]）被丢掉",
      not any(str(it.get("text") or "") in ("穴位打卡寻宝", "识艾护己，闯关同行", "[image]")
              for it in target.get("items") or []),
      [it.get("text") for it in target.get("items") or []])
eq("报送截止取更晚的 11-23 12:00", target.get("deadline"), "2026-11-23T12:00:00+08:00")
check("合并后标 supplement（已更新）", target.get("supplement") is True, target.get("supplement"))
check("归并幂等", [g.get("id") for g in bnb.merge_grouping_notices(merged_groups)] == ids, ids)

# ---------------------------------------------------------------- 11. 人工补丁 dropItems（2026-11-23）
print("---- §3.14 人工补丁 dropItems 精确删除条目 ----")
fd, tmp_name = tempfile.mkstemp(prefix="patch_", suffix=".json", dir=str(Path(__file__).parent))
os.close(fd)
tmp_patch = Path(tmp_name)
try:
    tmp_patch.write_text(json.dumps({"patches": [{
        "id": "g_drop_test", "dropItems": ["穴位打卡寻宝", "[image]"],
        "set": {"title": "军事理论课组队与分组"},
    }]}, ensure_ascii=False), encoding="utf-8")
    old_mp = bnb.MANUAL_PATCHES
    bnb.MANUAL_PATCHES = tmp_patch
    try:
        g_drop = {"id": "g_drop_test", "title": "旧标题",
                  "items": [{"kind": "text", "text": "穴位打卡寻宝"},
                            {"kind": "text", "text": "[image]"},
                            {"kind": "text", "text": "分组结果已出，请各组明天中午12点前把组名给学委"}]}
        bnb.apply_manual_patches([g_drop])
    finally:
        bnb.MANUAL_PATCHES = old_mp
    eq("dropItems 后剩 1 条", len(g_drop.get("items") or []), 1)
    check("保留分组正文", "组名" in str((g_drop.get("items") or [{}])[0].get("text") or ""),
          g_drop.get("items"))
    eq("补丁标题已写", g_drop.get("title"), "军事理论课组队与分组")
finally:
    try:
        tmp_patch.unlink()
    except OSError:
        pass
    bnb.MANUAL_SET_FIELDS.clear()

# ---------------------------------------------------------------- 结果
print("\n================ 结果 ================")
print("PASS %d / FAIL %d" % (PASS, FAIL))
if FAIL:
    print("失败用例：")
    for f in FAILED:
        print(" - " + f)
    sys.exit(1)
print("全部通过 ✅")
