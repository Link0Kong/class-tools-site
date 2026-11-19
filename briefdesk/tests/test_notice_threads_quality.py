# -*- coding: utf-8 -*-
"""builder 数据侧单测（2026-11-14 契约 §1.1/§1.4/§1.6）：更新合并 / 时间保护 / recurrence 校验。

覆盖：
  1) apply_threads：keep 覆盖最终有效字段、merge 组 items 改「补充通知」追加并删除、
     updatedAt 合并、容错（keep/merge id 不存在跳过）、重复应用幂等、顶层数组兼容；
  2) apply_quality 确定性时间保护：AI null 不误清 notice_time/原文可证的时间；
     非空照旧覆盖；AI notes 明确说明时间错误时允许清空；timeLabel 清理规则保持；
     ai_quality result.recurrence：缺省保持 / null 删除 / 对象替换；
  3) sanitize_recurrence：freq+HH:MM 门槛、无 time 丢弃、until（YYYY-MM-DD / ISO /
     非法 / 早于 startAt）、时间补零。

运行（任选）：
  C:\\briefdesk\\venv\\Scripts\\python.exe G:\\ClassTools\\web\\briefdesk\\tests\\test_notice_threads_quality.py
  python -m unittest briefdesk-plan\\tests\\test_notice_threads_quality.py -v

全部用临时文件 mock（不读写真实 AI 数据、不跑主线）。
"""
import json
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

BASE = Path(r"G:\ClassTools\web\briefdesk")
sys.path.insert(0, str(BASE))
sys.path.append(r"C:\briefdesk\scripts")

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import build_notice_board as bnb  # noqa: E402


def _write_json(path, obj):
    Path(path).write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")


class _TempFileCase(unittest.TestCase):
    """基类：临时目录 + 恢复被 monkeypatch 的模块常量。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="notice_builder_test_")
        self.tmp = Path(self._tmp.name)
        self._orig = {
            "AI_QUALITY": bnb.AI_QUALITY,
            "NOTICE_THREADS": bnb.NOTICE_THREADS,
            "MANUAL_SET_FIELDS": dict(bnb.MANUAL_SET_FIELDS),
        }
        bnb.MANUAL_SET_FIELDS.clear()

    def tearDown(self):
        bnb.AI_QUALITY = self._orig["AI_QUALITY"]
        bnb.NOTICE_THREADS = self._orig["NOTICE_THREADS"]
        bnb.MANUAL_SET_FIELDS.clear()
        bnb.MANUAL_SET_FIELDS.update(self._orig["MANUAL_SET_FIELDS"])
        self._tmp.cleanup()

    def use_quality(self, mapping):
        p = self.tmp / "ai-quality.json"
        _write_json(p, {"__ver": 2, "generatedAt": "2026-11-14T14:00:00+08:00",
                        "count": len(mapping), "groups": mapping})
        bnb.AI_QUALITY = p
        return p

    def use_threads(self, obj):
        p = self.tmp / "notice-threads.json"
        _write_json(p, obj)
        bnb.NOTICE_THREADS = p
        return p


# ================================================================ 1. apply_threads
class ThreadsTest(_TempFileCase):
    def _base_groups(self):
        keep = {
            "id": "g_keep", "cat": "军训", "title": "11-13起军训安排",
            "summary": "先发摘要", "aiSummary": "先发摘要", "aiPoints": ["先发"],
            "deadline": "2026-11-13T18:00:00+08:00",
            "items": [
                {"kind": "text", "label": "原始消息", "time": "11-12 10:00",
                 "text": "11-13 至 11-14 军训"},
            ],
        }
        merge = {
            "id": "g_merge", "cat": "军训", "title": "军训安排调整",
            "updatedAt": "2026-11-13T09:00:00+08:00",
            "items": [
                {"kind": "text", "label": "原始消息", "time": "11-13 09:00",
                 "from": "班长", "text": "周五周六不上晚自习了"},
            ],
        }
        return [keep, merge]

    def _thread(self, **over):
        th = {
            "keep": "g_keep",
            "merge": ["g_merge"],
            "title": "11-14、11-15军训；晚自习取消",
            "summary": "11-14、11-15军训；晚自习取消",
            "points": ["11-14 军训", "晚自习取消"],
            "segments": [{"type": "时间", "text": "11-14、11-15"}],
            "deadline": "2026-11-14T18:00:00+08:00",
            "reason": "后发消息取消晚自习，覆盖先发安排",
        }
        th.update(over)
        return th

    def test_merge_keep_and_drop(self):
        groups = self._base_groups()
        self.use_threads({"version": 1, "threads": [self._thread()]})
        out = bnb.apply_threads(groups)
        ids = [g["id"] for g in out]
        self.assertEqual(ids, ["g_keep"], "合并组必须删除，keep 组保留")
        keep = out[0]
        self.assertEqual(keep["title"], "11-14、11-15军训；晚自习取消")
        self.assertEqual(keep["aiSummary"], "11-14、11-15军训；晚自习取消")
        self.assertEqual(keep["aiPoints"], ["11-14 军训", "晚自习取消"])
        self.assertEqual(keep["aiSegments"], [{"type": "时间", "text": "11-14、11-15"}])
        self.assertEqual(keep["deadline"], "2026-11-14T18:00:00+08:00")
        self.assertTrue(keep.get("supplement"), "merge 后 keep 必须标 supplement")
        self.assertEqual(keep.get("updatedAt"), "2026-11-13T09:00:00+08:00",
                         "updatedAt 取被合并组的更新时间")
        self.assertEqual(keep.get("threadReason"), "后发消息取消晚自习，覆盖先发安排")  # ≤40 字
        # 追加的「补充通知」条目保留 time/from
        supp = [it for it in keep["items"] if it.get("label") == "补充通知"]
        self.assertEqual(len(supp), 1)
        self.assertEqual(supp[0]["text"], "周五周六不上晚自习了")
        self.assertEqual(supp[0]["time"], "11-13 09:00")
        self.assertEqual(supp[0]["from"], "班长")
        self.assertTrue(supp[0].get("supplement"))

    def test_idempotent(self):
        self.use_threads({"version": 1, "threads": [self._thread()]})
        once = bnb.apply_threads(self._base_groups())
        items_once = list(once[0]["items"])
        twice = bnb.apply_threads(once)
        self.assertEqual([g["id"] for g in twice], ["g_keep"])
        self.assertEqual(twice[0]["items"], items_once, "重复应用不得重复追加 items")
        self.assertEqual(len([it for it in twice[0]["items"] if it.get("label") == "补充通知"]), 1)

    def test_missing_ids_skipped(self):
        groups = self._base_groups()
        self.use_threads({"version": 1, "threads": [
            {"keep": "g_absent", "merge": ["g_merge"], "title": "x", "reason": "keep 不存在"},
            self._thread(merge=["g_merge", "g_absent_merge"]),
        ]})
        out = bnb.apply_threads(groups)
        self.assertEqual([g["id"] for g in out], ["g_keep"])
        self.assertEqual(out[0]["title"], "11-14、11-15军训；晚自习取消")
        self.assertEqual(len(out[0]["items"]), 2, "缺失的 merge id 跳过，其余照常合并")

    def test_keep_only_missing_leaves_groups(self):
        groups = self._base_groups()
        self.use_threads({"version": 1, "threads": [
            {"keep": "g_absent", "merge": ["g_merge"], "reason": "keep 不存在"}]})
        out = bnb.apply_threads(groups)
        self.assertEqual([g["id"] for g in out], ["g_keep", "g_merge"], "keep 不存在时不得删除任何组")

    def test_top_level_list_and_explicit_items(self):
        groups = self._base_groups()
        self.use_threads([{
            "keep": "g_keep",
            "merge": ["g_merge"],
            "items": [{"kind": "text", "label": "原始消息", "time": "11-13 12:00",
                       "text": "最终以后发消息为准"}],
            "reason": "顶层数组兼容",
        }])
        out = bnb.apply_threads(groups)
        self.assertEqual([g["id"] for g in out], ["g_keep"])
        texts = [it.get("text") for it in out[0]["items"]]
        self.assertIn("最终以后发消息为准", texts)
        self.assertIn("周五周六不上晚自习了", texts, "merge 组 items 仍在")

    def test_no_file_noop(self):
        bnb.NOTICE_THREADS = self.tmp / "not-exist.json"
        groups = self._base_groups()
        self.assertIs(bnb.apply_threads(groups), groups, "无 threads 文件原样返回")

    def test_manual_set_fields_protected(self):
        self.use_threads({"version": 1, "threads": [self._thread()]})
        bnb.apply_threads(self._base_groups())
        self.assertIn("deadline", bnb.MANUAL_SET_FIELDS.get("g_keep", set()),
                      "线程覆盖的时间字段必须登记，final 归一不得覆盖")

    def test_main_wiring_static(self):
        src = (BASE / "build_notice_board.py").read_text(encoding="utf-8")
        i_q = src.find("groups = apply_quality(groups)")
        i_t = src.find("groups = apply_threads(groups)")
        i_m = src.find("groups = apply_manual_patches(groups)")
        self.assertGreaterEqual(i_q, 0)
        self.assertGreater(i_t, i_q, "apply_threads 必须在 apply_quality 之后")
        self.assertLess(i_t, i_m, "apply_threads 必须在人工补丁之前")
        self.assertIn('NOTICE_THREADS = Path(r"C:\\briefdesk\\data\\notice-threads.json")', src)


# ================================================================ 2. apply_quality 时间保护
class QualityTimeProtectionTest(_TempFileCase):
    def _run(self, group, result):
        self.use_quality({str(group["id"]): {"result": result}})
        out = bnb.apply_quality([group])
        self.assertEqual(len(out), 1, "isNotice=true 的组不得被丢弃")
        return out[0]

    def test_eventAt_protected_when_notice_time_agrees(self):
        g = {
            "id": "g_shoot", "cat": "军训", "title": "射击人员集合",
            "eventAt": "2026-11-14T08:00:00+08:00",
            "items": [{"kind": "text", "time": "11-12 10:00",
                       "text": "射击人员11-14上午8:00在操场集合，不要迟到"}],
        }
        kept = self._run(g, {"isNotice": True, "confidence": 0.95, "eventAt": None})
        self.assertEqual(kept.get("eventAt"), "2026-11-14T08:00:00+08:00",
                         "notice_time 解析日期一致 → 必须保留 eventAt（契约 §1.6）")

    def test_deadline_protected_by_literal_date_token(self):
        g = {
            "id": "g_dl", "cat": "教务", "title": "材料提交",
            "signupStart": "2026-11-10T09:00:00+08:00",
            "items": [{"kind": "text", "time": "11-12 10:00", "text": "11-10 集合，请注意"}],
        }
        kept = self._run(g, {"isNotice": True, "confidence": 0.95,
                             "signupStart": None, "deadline": None})
        self.assertEqual(kept.get("signupStart"), "2026-11-10T09:00:00+08:00",
                         "原文出现该日期字面 → 视为确定性来源，保留现值")

    def test_cleared_when_no_deterministic_evidence(self):
        g = {
            "id": "g_clear", "cat": "教务", "title": "旧通知",
            "eventAt": "2026-11-21T08:00:00+08:00",
            "items": [{"kind": "text", "time": "11-12 10:00",
                       "text": "射击人员11-14上午8:00集合"}],
        }
        cleared = self._run(g, {"isNotice": True, "confidence": 0.95, "eventAt": None})
        self.assertNotIn("eventAt", cleared, "原文解析日期不同且无字面证据 → 按 AI 清空")

    def test_ai_null_with_notes_evidence_can_clear(self):
        g = {
            "id": "g_ev", "cat": "军训", "title": "射击人员集合",
            "eventAt": "2026-11-14T08:00:00+08:00",
            "items": [{"kind": "text", "time": "11-12 10:00",
                       "text": "射击人员11-14上午8:00在操场集合"}],
        }
        cleared = self._run(g, {"isNotice": True, "confidence": 0.95, "eventAt": None,
                                "notes": "系统解析的集合时间错误，实际安排已取消"})
        self.assertNotIn("eventAt", cleared, "AI notes 明确说明时间有误 → 允许清空")

    def test_non_null_ai_value_still_overwrites(self):
        g = {
            "id": "g_ow", "cat": "教务", "title": "通知",
            "deadline": "2026-11-20T18:00:00+08:00", "timeLabel": "报名 11-20 18:00",
            "items": [{"kind": "text", "time": "11-12 10:00", "text": "请于11月20日18:00前提交"}],
        }
        out = self._run(g, {"isNotice": True, "confidence": 0.95,
                            "deadline": "2026-11-19T20:00:00+08:00"})
        self.assertEqual(out.get("deadline"), "2026-11-19T20:00:00+08:00")
        self.assertNotIn("timeLabel", out, "时间被 AI 纠正后旧文案必须清掉")

    def test_ai_recurrence_null_deletes(self):
        g = {"id": "g_r", "cat": "军训", "title": "请假",
             "recurrence": {"freq": "daily", "time": "07:30"},
             "items": [{"kind": "text", "time": "11-12 10:00", "text": "每日 07:30 前私发导员请假"}]}
        out = self._run(g, {"isNotice": True, "confidence": 0.95, "recurrence": None})
        self.assertNotIn("recurrence", out, "recurrence:null 表示 AI 明确删除")

    def test_ai_recurrence_object_replaces(self):
        g = {"id": "g_r2", "cat": "军训", "title": "请假",
             "recurrence": {"freq": "daily", "time": "07:30"},
             "items": [{"kind": "text", "time": "11-12 10:00", "text": "每日 07:30 前私发导员请假"}]}
        new = {"freq": "daily", "time": "07:30", "startAt": "2026-11-10T07:30:00+08:00",
               "until": "2026-11-15"}
        out = self._run(g, {"isNotice": True, "confidence": 0.95, "recurrence": new})
        self.assertEqual(out.get("recurrence"), new)

    def test_ai_recurrence_missing_key_keeps(self):
        g = {"id": "g_r3", "cat": "军训", "title": "请假",
             "recurrence": {"freq": "daily", "time": "07:30"},
             "items": [{"kind": "text", "time": "11-12 10:00", "text": "每日 07:30 前私发导员请假"}]}
        out = self._run(g, {"isNotice": True, "confidence": 0.95, "isNoticeNote": ""})
        self.assertEqual(out.get("recurrence"), {"freq": "daily", "time": "07:30"})


# ================================================================ 3. recurrence 校验
class RecurrenceSanitizeTest(unittest.TestCase):
    def _g(self, rec):
        return {"id": "g", "title": "t", "recurrence": rec}

    def test_valid_monthly_weeks_until_date(self):
        g = self._g({"freq": "monthly_weeks", "weekday": 3, "weeks": [1, 2, 3],
                     "time": "17:30", "startAt": "2026-11-04T17:30:00+08:00",
                     "until": "2026-12-31", "label": "每月前三周 周三 17:30"})
        bnb.sanitize_recurrence(g)
        rec = g["recurrence"]
        self.assertEqual(rec["freq"], "monthly_weeks")
        self.assertEqual(rec["time"], "17:30")
        self.assertEqual(rec["until"], "2026-12-31")
        self.assertEqual(rec["label"], "每月前三周 周三 17:30", "校验不得丢其他字段")
        self.assertEqual(rec["weeks"], [1, 2, 3])

    def test_valid_iso_until(self):
        g = self._g({"freq": "daily", "time": "07:30", "startAt": "2026-11-10T07:30:00+08:00",
                     "until": "2026-11-15T23:59:00+08:00"})
        bnb.sanitize_recurrence(g)
        self.assertEqual(g["recurrence"]["until"], "2026-11-15T23:59:00+08:00")

    def test_invalid_until_dropped_but_recurrence_kept(self):
        g = self._g({"freq": "daily", "time": "07:30", "startAt": "2026-11-10T07:30:00+08:00",
                     "until": "2026-11-99"})
        bnb.sanitize_recurrence(g)
        self.assertIn("recurrence", g)
        self.assertNotIn("until", g["recurrence"], "非法 until 只丢弃字段")

    def test_until_before_start_dropped(self):
        g = self._g({"freq": "daily", "time": "07:30", "startAt": "2026-11-10T07:30:00+08:00",
                     "until": "2026-11-09"})
        bnb.sanitize_recurrence(g)
        self.assertNotIn("until", g["recurrence"], "until 早于 startAt → 丢弃 until")

    def test_missing_time_drops_recurrence(self):
        g = self._g({"freq": "daily", "startAt": "2026-11-10T07:30:00+08:00"})
        bnb.sanitize_recurrence(g)
        self.assertNotIn("recurrence", g, "无 time 的 recurrence 一律丢弃（契约 §1.1）")

    def test_bad_time_drops_recurrence(self):
        for bad in ("25:00", "12:60", "7点半", "07-30", ""):
            g = self._g({"freq": "daily", "time": bad})
            bnb.sanitize_recurrence(g)
            self.assertNotIn("recurrence", g, "非法 time 必须丢弃: %r" % bad)

    def test_bad_freq_drops_recurrence(self):
        for bad in ("yearly", "", None):
            rec = {"freq": bad, "time": "07:30"} if bad is not None else {"time": "07:30"}
            g = self._g(rec)
            bnb.sanitize_recurrence(g)
            self.assertNotIn("recurrence", g, "非法 freq 必须丢弃: %r" % (bad,))

    def test_time_normalized(self):
        g = self._g({"freq": "Daily", "time": "7:5"})
        # 7:5 不符合 HH:MM（分钟需 2 位）→ 丢弃；再测 7:30 补零
        bnb.sanitize_recurrence(g)
        self.assertNotIn("recurrence", g)
        g2 = self._g({"freq": "Daily", "time": "7:30"})
        bnb.sanitize_recurrence(g2)
        self.assertEqual(g2["recurrence"]["freq"], "daily")
        self.assertEqual(g2["recurrence"]["time"], "07:30")

    def test_non_dict_recurrence_dropped(self):
        for bad in ("daily", [], 0):
            g = self._g(bad)
            bnb.sanitize_recurrence(g)
            self.assertNotIn("recurrence", g)

    def test_sanitize_recurrences_list(self):
        groups = [self._g({"freq": "daily", "time": "07:30"}),
                  self._g({"freq": "daily"}), {"id": "x", "title": "无 recurrence"}]
        bnb.sanitize_recurrences(groups)
        self.assertIn("recurrence", groups[0])
        self.assertNotIn("recurrence", groups[1])
        self.assertNotIn("recurrence", groups[2])


if __name__ == "__main__":
    unittest.main(verbosity=2)
