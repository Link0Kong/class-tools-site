# -*- coding: utf-8 -*-
"""通知 × 课表联动：把「某门课 + 课前动作」类通知锚到该课实际上课时间。

用户需求（2026-11-23）：
    「思政三组 11-23（今天）提前到教室拷演讲内容」应设成「思政课前」，
    而不是日终兜底的 23:59。

判定全部是确定性的（不依赖 AI 是否听话）：
  1. 正文出现课程名/别名（思政、高数、C语言、英语、体育、中医、军理、形策、计算机…）；
  2. 正文出现「课前」动作（课前 / 上课前 / 提前到教室 / 提前到班 / 到教室拷带交…）；
  3. 正文（或现有 deadline/eventAt）能推出日期，且该日期课表里确有这门课
     （开学周 + 教学周 + 单双周 + 星期全部命中）；
  4. 现有截止缺失、或只是「当天 23:59」这类日终兜底、或比上课时间更晚 →
     改成上课开始时间，动作文案写成「<课程>课前」，并写 courseAnchor 供三端展示/排查。

边界（不覆盖）：
  * 长期安排（recurrence）不做锚定；
  * AI 质检明确判过期的卡不动；
  * 已有明确且早于上课时间的截止（如「11-23 07:30 前交」）不动；
  * 人工补丁在 builder 里后应用，人工值优先。

课表口径与网页 `tools/index.html` 的 `PERIODS`、安卓 `TtPeriods` 一致（12 节，北京时间）。
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

# 网页/安卓/小程序共用的节次时间（Asia/Shanghai）
PERIODS = (
    ("08:10", "08:50"),
    ("09:00", "09:40"),
    ("09:50", "10:30"),
    ("10:40", "11:20"),
    ("11:30", "12:10"),
    ("14:30", "15:10"),
    ("15:20", "16:00"),
    ("16:10", "16:50"),
    ("17:00", "17:40"),
    ("19:00", "19:40"),
    ("19:50", "20:30"),
    ("20:40", "21:20"),
)

# 默认课表快照：web/tools/tt.json（jwxt 同步产物；env CLASS_TT_JSON 可覆盖）
DEFAULT_TT_JSON = Path(__file__).resolve().parent.parent / "tools" / "tt.json"

# (课前文案短名, 正文别名正则, 课表课程名片段)
# 顺序 = 匹配优先级；短名 + 「课前」必须 ≤6 字（三端 chip 动作上限）。
COURSE_RULES = (
    ("思政", re.compile(r"思政|思想道德|道德与法治|思修"), ("思想道德与法治", "思想道德")),
    ("高数", re.compile(r"高数|高等数学"), ("高等数学",)),
    ("C语言", re.compile(r"C\s*语言|C程序设计|C程序"), ("C语言",)),
    ("英语", re.compile(r"英语|大学英语"), ("英语",)),
    ("体育", re.compile(r"体育"), ("体育",)),
    ("中医", re.compile(r"中医学|中医"), ("中医学", "中医")),
    ("军理", re.compile(r"军事理论|军理"), ("军事理论",)),
    ("形策", re.compile(r"形势与政策|形策"), ("形势与政策",)),
    ("计算机", re.compile(r"Python|python|计算机导论|计算机科学导论"), ("计算机科学导论", "Python")),
)

# 课前动作：只认「明确要提前到教室/上课前」的表述，避免把「提前完成」误判
_PRECLASS_RE = re.compile(
    r"课前|上课前|上课之前|开课前|进教室前"
    r"|提前(?:到|去|来|入场|进场|到教室|到班|到课室|到教学楼|到校)"
    r"|(?:到教室|到班|到课室|进教室)(?:拷|考|拷贝|带|交|准备|集合|签到)"
)

# 相对日（只用消息时间做锚点，不用「现在」，避免重建时漂移）
_REL_DAY = (
    ("大后天", 3), ("后天", 2),
    ("明天", 1), ("明日", 1), ("明早", 1), ("明晚", 1),
    ("今天", 0), ("今日", 0), ("今早", 0), ("今晚", 0),
)
_WEEKDAY_CN = {"一": 0, "二": 1, "三": 2, "四": 3, "五": 4, "六": 5, "日": 6, "天": 6}
_WEEK_WORD_RE = re.compile(r"(?:本周|这周|下)?(?:周|星期|礼拜)([一二三四五六日天])")
_MD_RE = re.compile(r"(?<!\d)(\d{1,2})\s*[-/.]\s*(\d{1,2})(?!\d)")
_CN_DATE_RE = re.compile(r"(?:(20\d{2})\s*年\s*)?(\d{1,2})\s*月\s*(\d{1,2})\s*[日号]?")

_TZ = "+08:00"
_CN_TZ = timezone(timedelta(hours=8))


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + _TZ


def _parse_iso(value):
    if not value:
        return None
    s = str(value).strip()
    if not s:
        return None
    try:
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is not None:
        # 统一换算成北京时间钟面（课表节次时间按 Asia/Shanghai 解释，不受设备时区影响）
        dt = dt.astimezone(_CN_TZ).replace(tzinfo=None)
    return dt


def load_timetable(path=None):
    """读课表快照（失败返回 None，调用方 fail-open 不锚定）。"""
    p = Path(path) if path else DEFAULT_TT_JSON
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(raw, dict):
        return None
    courses = [c for c in (raw.get("c") or []) if isinstance(c, dict) and str(c.get("name") or "").strip()]
    term_start = _parse_iso(str(raw.get("t") or ""))
    if not courses or term_start is None:
        return None
    return {
        "termStart": term_start.date(),
        "courses": courses,
        "source": str(raw.get("meta", {}).get("term") or ""),
    }


def _parse_weeks(text):
    """'13-18' / '2-3,5,7-10' → set[int]；空 = 全学期（返回 None）。"""
    s = str(text or "").strip()
    if not s:
        return None
    weeks = set()
    for part in re.split(r"[,，]", s):
        part = part.strip()
        if not part:
            continue
        m = re.match(r"^(\d+)\s*[-~—]\s*(\d+)$", part)
        if m:
            a, b = int(m.group(1)), int(m.group(2))
            if 1 <= a <= b <= 60:
                weeks.update(range(a, b + 1))
        elif part.isdigit() and 1 <= int(part) <= 60:
            weeks.add(int(part))
    return weeks or None


def _course_active(course, week):
    weeks = _parse_weeks(course.get("weeks"))
    if weeks is not None and week not in weeks:
        return False
    parity = str(course.get("parity") or "").strip()
    if parity == "odd" and week % 2 == 0:
        return False
    if parity == "even" and week % 2 == 1:
        return False
    return True


def _name_matches(name, fragments):
    n = str(name or "")
    return any(f and f in n for f in fragments)


def match_course(text):
    """正文 → (短名, 课表课程名片段, 匹配位置)；多个命中取最早出现、再按规则顺序。"""
    s = str(text or "")
    if not s:
        return None
    best = None
    for order, (short, regex, fragments) in enumerate(COURSE_RULES):
        m = regex.search(s)
        if not m:
            continue
        key = (m.start(), order)
        if best is None or key < best[0]:
            best = (key, short, fragments)
    if best is None:
        return None
    return best[1], best[2], best[0][0]


def has_preclass_cue(text):
    return bool(_PRECLASS_RE.search(str(text or "")))


def _add_days(d, delta):
    return d + timedelta(days=delta)


def _parse_md(text, ref_date):
    """正文里的 MM-DD / M月D日 → datetime.date（按锚点年份；跨年滚动）。"""
    out = []
    for m in _MD_RE.finditer(text):
        mo, da = int(m.group(1)), int(m.group(2))
        if not (1 <= mo <= 12 and 1 <= da <= 31):
            continue
        try:
            d = datetime(ref_date.year, mo, da).date()
        except ValueError:
            continue
        if (ref_date - d).days > 180:  # 12 月的通知里写 1-05 → 明年
            try:
                d = datetime(ref_date.year + 1, mo, da).date()
            except ValueError:
                continue
        out.append((m.start(), d))
    for m in _CN_DATE_RE.finditer(text):
        year = int(m.group(1)) if m.group(1) else ref_date.year
        mo, da = int(m.group(2)), int(m.group(3))
        if not (1 <= mo <= 12 and 1 <= da <= 31):
            continue
        try:
            out.append((m.start(), datetime(year, mo, da).date()))
        except ValueError:
            continue
    out.sort(key=lambda x: x[0])
    # 同一天只留第一次出现的位置
    seen, uniq = set(), []
    for pos, d in out:
        if d in seen:
            continue
        seen.add(d)
        uniq.append((pos, d))
    return uniq


def _text_dates(text, ref_dt):
    """正文日期（相对日先替换成具体日期），按出现顺序返回 date 列表。"""
    s = str(text or "")
    ref_date = ref_dt.date()
    # 「今日校园」是专有名词（教务 App），里面的「今日」不是日期
    s = s.replace("今日校园", "\x00校园")

    def rel_sub(m):
        word = m.group(0)
        for w, delta in _REL_DAY:
            if word == w:
                return "%04d-%02d-%02d" % tuple(_add_days(ref_date, delta).timetuple()[:3])
        return word

    rel_re = re.compile("|".join(re.escape(w) for w, _ in _REL_DAY))
    s = rel_re.sub(rel_sub, s)

    # 周X / 星期X：取锚点之后的最近一次（含当天）
    def week_sub(m):
        wd = _WEEKDAY_CN.get(m.group(1))
        if wd is None:
            return m.group(0)
        delta = (wd - ref_date.weekday()) % 7
        return "%04d-%02d-%02d" % tuple(_add_days(ref_date, delta).timetuple()[:3])

    s = _WEEK_WORD_RE.sub(week_sub, s)
    return [d for _pos, d in _parse_md(s, ref_date)]


def _course_text(group):
    """参与判定的正文：标题/摘要/AI 要点/明细文本（不含附件名/URL，避免误命中）。"""
    parts = [
        group.get("title"), group.get("summary"), group.get("aiSummary"),
    ]
    for key in ("aiPoints",):
        for item in group.get(key) or []:
            if isinstance(item, str):
                parts.append(item)
    for seg in group.get("aiSegments") or []:
        if isinstance(seg, dict):
            parts.append(seg.get("text"))
    for it in group.get("items") or []:
        if not isinstance(it, dict):
            continue
        if it.get("kind") in ("text", "follow"):
            parts.append(it.get("text") or it.get("body"))
        elif it.get("kind") in ("form", "link"):
            parts.append(it.get("name") or it.get("realTitle"))
    return " ".join(str(p) for p in parts if p)


def _group_ref_time(group, now=None):
    """消息锚点时间：第一条 item.time（MM-DD HH:MM）→ datetime；无则 None。"""
    for it in group.get("items") or []:
        if isinstance(it, dict) and it.get("time"):
            m = re.match(r"^(\d{1,2})-(\d{1,2})\s+(\d{1,2}):(\d{2})$", str(it["time"]).strip())
            if not m:
                continue
            base = now or datetime.now()
            try:
                dt = datetime(base.year, int(m.group(1)), int(m.group(2)),
                              int(m.group(3)), int(m.group(4)))
            except ValueError:
                continue
            if dt > base + timedelta(days=60):
                try:
                    dt = datetime(base.year - 1, dt.month, dt.day, dt.hour, dt.minute)
                except ValueError:
                    continue
            return dt
    return None


def _session_on(timetable, fragments, date):
    """某门课在指定日期的课表占用（取最早开始的一节）；没有返回 None。"""
    term_start = timetable["termStart"]
    week = (date - term_start).days // 7 + 1
    if week < 1 or week > 30:
        return None
    best = None
    for course in timetable["courses"]:
        try:
            day = int(course.get("day"))
            start = int(course.get("start"))
            end = int(course.get("end"))
        except (TypeError, ValueError):
            continue
        if day != date.weekday() or not _name_matches(course.get("name"), fragments):
            continue
        if not (1 <= start <= end <= len(PERIODS)):
            continue
        if not _course_active(course, week):
            continue
        if best is None or start < best["start"]:
            best = {
                "name": str(course.get("name") or "").strip(),
                "teacher": str(course.get("teacher") or "").strip(),
                "room": str(course.get("room") or "").strip(),
                "day": day, "start": start, "end": end, "week": week,
                "date": date.isoformat(),
                "startText": PERIODS[start - 1][0],
                "endText": PERIODS[end - 1][1],
            }
    if best is not None:
        best["startAt"] = _iso(datetime.combine(date, datetime.strptime(best["startText"], "%H:%M").time()))
        best["endAt"] = _iso(datetime.combine(date, datetime.strptime(best["endText"], "%H:%M").time()))
    return best


def detect_course_anchor(group, timetable=None, now=None):
    """一张通知 → 课表锚点 dict；不该锚定返回 None。"""
    if not isinstance(group, dict):
        return None
    if isinstance(group.get("recurrence"), dict) and group["recurrence"].get("freq"):
        return None
    if group.get("expired") is True:
        return None
    text = _course_text(group)
    if not text:
        return None
    course = match_course(text)
    if course is None:
        return None
    short, fragments, _pos = course
    if not has_preclass_cue(text):
        return None
    tt = timetable or load_timetable()
    if not tt:
        return None
    ref_dt = _group_ref_time(group, now) or (now or datetime.now())
    candidates = []
    for d in _text_dates(text, ref_dt):
        if d >= ref_dt.date():
            candidates.append(d)
    for key in ("deadline", "eventAt"):
        dt = _parse_iso(group.get(key))
        if dt is not None and dt.date() >= ref_dt.date():
            candidates.append(dt.date())
    if not candidates:
        candidates.append(ref_dt.date())
    # 同一天只保留一次，按出现顺序
    seen, ordered = set(), []
    for d in candidates:
        if d not in seen:
            seen.add(d)
            ordered.append(d)
    for date in ordered:
        session = _session_on(tt, fragments, date)
        if not session:
            continue
        start_dt = _parse_iso(session["startAt"])
        # 只锚「消息发出时还没开始」的课，避免把已上完的课当未来截止
        if start_dt is None or start_dt <= ref_dt:
            continue
        label = (short + "课前")[:6]
        session["short"] = short
        session["label"] = label
        return session
    return None


def _is_end_of_day(dt):
    return dt is not None and dt.hour >= 23 and dt.minute >= 30


def _should_override(deadline, start_dt):
    """现有截止是否应被上课时间替换。

    只有三类可以改：没有截止、日终兜底（23:59）、比上课时间更晚。
    明确早于上课时间的截止保持原样（不把用户/老师的硬截止改晚）。
    """
    if deadline is None:
        return True
    if _is_end_of_day(deadline):
        return True
    return deadline > start_dt


def _is_own_anchor(deadline, previous_anchor):
    """当前 deadline 是否就是上一次课表联动的锚点（课表调整时要跟着改，不当成硬截止）。"""
    if not isinstance(previous_anchor, dict):
        return False
    prev_start = _parse_iso(previous_anchor.get("startAt"))
    if prev_start is None or deadline is None:
        return False
    return abs((deadline - prev_start).total_seconds()) <= 60


def _clear_anchor(group):
    """不再符合锚定条件：清 courseAnchor，并把它改过的 deadline/动作还原。"""
    prev = group.get("courseAnchor")
    if not isinstance(prev, dict):
        return
    group.pop("courseAnchor", None)
    cur = _parse_iso(group.get("deadline"))
    if not _is_own_anchor(cur, prev):
        return  # 截止已被人工/AI 改成别的值，不还原
    if "prevDeadline" in prev:
        if prev.get("prevDeadline"):
            group["deadline"] = prev["prevDeadline"]
        else:
            group.pop("deadline", None)
    if "prevAction" in prev:
        if prev.get("prevAction"):
            group["deadlineAction"] = prev["prevAction"]
        else:
            group.pop("deadlineAction", None)


def apply_course_anchors(groups, timetable=None, now=None):
    """原地给通知组写 courseAnchor / deadline / deadlineAction；返回 groups。"""
    if not groups:
        return groups
    tt = timetable
    if tt is None:
        tt = load_timetable()
    if not tt:
        return groups
    for group in groups:
        if not isinstance(group, dict):
            continue
        # AI 已判过期的卡保持原状（既有 courseAnchor 也保留，展示仍为「课前」口径）
        if group.get("expired") is True:
            continue
        anchor = detect_course_anchor(group, tt, now)
        if anchor is None:
            _clear_anchor(group)
            continue
        start_dt = _parse_iso(anchor["startAt"])
        if start_dt is None:
            continue
        deadline = _parse_iso(group.get("deadline"))
        previous = group.get("courseAnchor") if isinstance(group.get("courseAnchor"), dict) else None
        own = _is_own_anchor(deadline, previous)
        # 记录锚定前的原值，便于课表变动后还原（沿用最早一次的 prev，避免把自家时间当原值）
        if own and previous is not None:
            anchor["prevDeadline"] = previous.get("prevDeadline")
            anchor["prevAction"] = previous.get("prevAction")
        else:
            anchor["prevDeadline"] = group.get("deadline") or None
            anchor["prevAction"] = group.get("deadlineAction") or None
        if own or _should_override(deadline, start_dt):
            group["deadline"] = anchor["startAt"]
            group["deadlineAction"] = anchor["label"]
        group["courseAnchor"] = anchor
    return groups
