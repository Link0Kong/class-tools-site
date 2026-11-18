# -*- coding: utf-8 -*-
"""test_health_pg_monitor.py — P4「PG 监控并入 cloudbase 行」离线单测（不联网、不写任何后端）。

被测对象：deploy/functions/health_probe/health_beat.py（ECS health_probe job 实际部署的副本）。
覆盖：
  * 解析/归一化（监控 JSON 数字是字符串，ts 是 ISO UTC）；损坏/缺失返回 None；
  * pg_monitor_status 五态：ok / warn(ok=false 带原因) / missing / stale(>30min) / invalid(ts 无法解析)；
  * attach_pg_monitor：仅 staging/selfhosted 生效；CloudBase 模式原样返回；本机无监控目录优雅跳过；
    降级只把 ok→warn，detail 追加原因且 ≤60 字，meta.pg 字段完整；不修改入参 row；
  * detect_cloudbase 集成：staging 模式带 meta.pg，CloudBase 模式 detail/meta 与 P3 完全一致；
  * 18 行契约：SERVICE_DEFS 仍 18 行、cloudbase 行 id 不变。

运行：C:\\briefdesk\\venv\\Scripts\\python.exe deploy\\functions\\tests\\test_health_pg_monitor.py
"""
import importlib.util
import json
import os
import sys
import tempfile
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
HB_PATH = HERE.parent / "health_probe" / "health_beat.py"

_spec = importlib.util.spec_from_file_location("hp_health_beat", str(HB_PATH))
hb = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(hb)  # noqa: E402

STAGING_BASE = "http://121.196.47.2/v1/rdb/rest-next/"
CLOUDBASE_BASE = "https://tool-d4gosudok46e0e081.api.tcloudbasegateway.com/v1/rdb/rest/"


def _iso(minutes_ago=0):
    return (datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)).isoformat(
        timespec="seconds")


def _monitor(**over):
    """构造与 ECS 实际文件同构的监控 JSON（数字都是字符串）。"""
    data = {
        "pg_active": "active",
        "pgrest_active": "active",
        "pgrest_http": "200",
        "staging_http": "200",
        "backup_file": "/opt/class-tools/backup/pg/class_tools-20261118-141238.dump",
        "backup_age_h": "1",
        "disk_use_pct": "23",
        "connections": "15",
        "db_size": "73MB",
        "backup_count": "3",
        "prod_mode": "cloudbase",
        "ok": True,
        "ts": _iso(0),
    }
    data.update(over)
    return data


def _row(status="ok", detail="HTTP 200 · 3ms", meta=None):
    return {
        "id": "cloudbase",
        "name": "云端数据库",
        "kind": "cloud",
        "status": status,
        "detail": detail,
        "meta": dict(meta or {"url": STAGING_BASE + "service_health", "backend": "staging"}),
        "checked_at": int(time.time() * 1000),
    }


class TestReadMonitor(unittest.TestCase):
    def test_read_normalizes_string_numbers(self):
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "pg-monitor.json")
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(_monitor(), fh)
            rec = hb.read_pg_monitor(path)
        self.assertIsNotNone(rec)
        self.assertTrue(rec["ok"])
        self.assertEqual(rec["connections"], 15.0)
        self.assertEqual(rec["disk_use_pct"], 23.0)
        self.assertEqual(rec["backup_age_h"], 1.0)
        self.assertEqual(rec["backup_count"], 3.0)
        self.assertEqual(rec["pg_active"], "active")
        self.assertEqual(rec["db_size"], "73MB")
        self.assertEqual(rec["prod_mode"], "cloudbase")
        self.assertLessEqual(rec["age_min"], 2.0)
        self.assertEqual(rec["backup_file"], "class_tools-20261118-141238.dump")  # 只留文件名

    def test_read_missing_or_corrupt_returns_none(self):
        with tempfile.TemporaryDirectory() as td:
            self.assertIsNone(hb.read_pg_monitor(os.path.join(td, "nope.json")))
            bad = os.path.join(td, "bad.json")
            with open(bad, "w", encoding="utf-8") as fh:
                fh.write("{not json")
            self.assertIsNone(hb.read_pg_monitor(bad))
            arr = os.path.join(td, "arr.json")
            with open(arr, "w", encoding="utf-8") as fh:
                fh.write("[1,2,3]")
            self.assertIsNone(hb.read_pg_monitor(arr))

    def test_num_helper(self):
        self.assertEqual(hb._num("15"), 15.0)
        self.assertEqual(hb._num("23%"), 23.0)
        self.assertEqual(hb._num(7), 7.0)
        self.assertIsNone(hb._num(""))
        self.assertIsNone(hb._num(None))
        self.assertIsNone(hb._num(True))


class TestStatus(unittest.TestCase):
    def test_ok(self):
        state, suffix, reasons = hb.pg_monitor_status(hb.read_pg_monitor(self._tmp(_monitor())))
        self.addCleanup(self._cleanup)
        self.assertEqual(state, "ok")
        self.assertIn("PG ok", suffix)
        self.assertIn("15 连接", suffix)
        self.assertIn("23% 磁盘", suffix)
        self.assertIn("备份 1h", suffix)
        self.assertEqual(reasons, [])

    def test_warn_ok_false_reasons(self):
        rec = hb.read_pg_monitor(self._tmp(_monitor(
            ok=False, backup_age_h="99", disk_use_pct="91", connections="75")))
        self.addCleanup(self._cleanup)
        state, suffix, reasons = hb.pg_monitor_status(rec)
        self.assertEqual(state, "warn")
        self.assertIn("PG 异常", suffix)
        self.assertTrue(any("备份" in r for r in reasons))
        self.assertTrue(any("磁盘" in r for r in reasons))
        self.assertTrue(any("连接" in r for r in reasons))

    def test_stale(self):
        rec = hb.read_pg_monitor(self._tmp(_monitor(ts=_iso(31))))
        self.addCleanup(self._cleanup)
        state, suffix, _ = hb.pg_monitor_status(rec)
        self.assertEqual(state, "stale")
        self.assertIn("过期", suffix)
        self.assertIn("31", suffix)

    def test_missing_and_invalid(self):
        self.assertEqual(hb.pg_monitor_status(None)[0], "missing")
        rec = hb.read_pg_monitor(self._tmp(_monitor(ts="not-a-time")))
        self.addCleanup(self._cleanup)
        state, suffix, _ = hb.pg_monitor_status(rec)
        self.assertEqual(state, "invalid")
        self.assertIn("时间无效", suffix)

    # -- 小工具：把 dict 写成临时监控文件，返回路径（cleanup 里删目录）
    def _tmp(self, data):
        self._td = tempfile.TemporaryDirectory()
        path = os.path.join(self._td.name, "pg-monitor.json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False)
        return path

    def _cleanup(self):
        try:
            self._td.cleanup()
        except Exception:  # noqa: BLE001
            pass


class TestAttach(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.dir = self._td.name
        self.path = os.path.join(self.dir, "pg-monitor.json")

    def tearDown(self):
        self._td.cleanup()

    def _write(self, **over):
        with open(self.path, "w", encoding="utf-8") as fh:
            json.dump(_monitor(**over), fh)
        return self.path

    def test_cloudbase_mode_untouched(self):
        """CloudBase 默认模式：即使监控文件存在也完全不读，行与 P3 完全一致。"""
        self._write()
        row = _row()
        out = hb.attach_pg_monitor(row, "cloudbase", path=self.path)
        self.assertEqual(out, row)
        self.assertNotIn("pg", out["meta"])
        self.assertEqual(out["detail"], "HTTP 200 · 3ms")

    def test_staging_fresh_ok(self):
        self._write()
        row = _row()
        out = hb.attach_pg_monitor(row, "staging", path=self.path)
        self.assertEqual(out["status"], "ok")
        self.assertEqual(out["detail"], "HTTP 200 · 3ms · PG ok · 15 连接 · 23% 磁盘 · 备份 1h")
        self.assertLessEqual(len(out["detail"]), 60)
        pg = out["meta"]["pg"]
        self.assertEqual(pg["status"], "ok")
        self.assertTrue(pg["expected"])
        self.assertTrue(pg["ok"])
        self.assertEqual(pg["connections"], 15.0)
        self.assertEqual(pg["source"], self.path)
        self.assertEqual(row["meta"], {"url": STAGING_BASE + "service_health", "backend": "staging"})
        self.assertEqual(row["detail"], "HTTP 200 · 3ms")   # 不修改入参

    def test_selfhosted_same_as_staging(self):
        self._write()
        out = hb.attach_pg_monitor(_row(), "selfhosted", path=self.path)
        self.assertEqual(out["status"], "ok")
        self.assertIn("PG ok", out["detail"])
        self.assertEqual(out["meta"]["pg"]["status"], "ok")

    def test_staging_ok_false_downgrades(self):
        self._write(ok=False, backup_age_h="99")
        out = hb.attach_pg_monitor(_row(), "staging", path=self.path)
        self.assertEqual(out["status"], "warn")
        self.assertIn("PG 异常", out["detail"])
        self.assertIn("备份99h", out["detail"])
        self.assertLessEqual(len(out["detail"]), 60)
        self.assertEqual(out["meta"]["pg"]["status"], "warn")
        self.assertTrue(out["meta"]["pg"]["reasons"])

    def test_staging_stale_downgrades(self):
        self._write(ts=_iso(35))
        out = hb.attach_pg_monitor(_row(), "staging", path=self.path)
        self.assertEqual(out["status"], "warn")
        self.assertIn("过期", out["detail"])
        self.assertEqual(out["meta"]["pg"]["status"], "stale")

    def test_missing_file_downgrades(self):
        self.assertFalse(os.path.exists(self.path))
        out = hb.attach_pg_monitor(_row(), "staging", path=self.path)
        self.assertEqual(out["status"], "warn")
        self.assertIn("缺失", out["detail"])
        self.assertEqual(out["meta"]["pg"]["status"], "missing")

    def test_corrupt_file_downgrades(self):
        with open(self.path, "w", encoding="utf-8") as fh:
            fh.write("{broken")
        out = hb.attach_pg_monitor(_row(), "staging", path=self.path)
        self.assertEqual(out["status"], "warn")
        self.assertEqual(out["meta"]["pg"]["status"], "missing")

    def test_no_monitor_dir_skips_gracefully(self):
        """本机（Windows）没有 /var/lib/class-tools：staging 模式下优雅跳过，不改状态。"""
        missing_path = os.path.join(self.dir, "nope-dir", "pg-monitor.json")
        row = _row()
        out = hb.attach_pg_monitor(row, "staging", path=missing_path)
        self.assertEqual(out["status"], "ok")
        self.assertEqual(out["detail"], row["detail"])
        self.assertTrue(out["meta"]["pg"]["skipped"])
        self.assertEqual(out["meta"]["pg"]["reason"], "no-monitor-file-on-host")

    def test_down_row_not_upgraded(self):
        self._write()
        out = hb.attach_pg_monitor(_row(status="down", detail="不可用：HTTP 500"), "staging",
                                   path=self.path)
        self.assertEqual(out["status"], "down")            # 只降不升
        self.assertIn("PG ok", out["detail"])


class TestDetectCloudbaseIntegration(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.path = os.path.join(self._td.name, "pg-monitor.json")
        with open(self.path, "w", encoding="utf-8") as fh:
            json.dump(_monitor(), fh)
        self._old_env = os.environ.get("CLASS_PG_MONITOR")
        os.environ["CLASS_PG_MONITOR"] = self.path
        self._old_http = hb.http_get
        hb.http_get = lambda *a, **k: (200, b"[]", 3, None)

    def tearDown(self):
        hb.http_get = self._old_http
        if self._old_env is None:
            os.environ.pop("CLASS_PG_MONITOR", None)
        else:
            os.environ["CLASS_PG_MONITOR"] = self._old_env
        self._td.cleanup()

    def test_staging_has_pg(self):
        row = hb.detect_cloudbase(STAGING_BASE, "k", None)
        self.assertEqual(row["id"], "cloudbase")
        self.assertEqual(row["status"], "ok")
        self.assertEqual(row["meta"]["backend"], "staging")
        self.assertIn("PG ok", row["detail"])
        self.assertEqual(row["meta"]["pg"]["status"], "ok")

    def test_cloudbase_unchanged(self):
        row = hb.detect_cloudbase(CLOUDBASE_BASE, "k", None)
        self.assertEqual(row["status"], "ok")
        self.assertEqual(row["detail"], "HTTP 200 · 3ms")
        self.assertNotIn("pg", row["meta"])
        self.assertEqual(row["meta"]["backend"], "cloudbase")

    def test_contract_18_rows(self):
        self.assertEqual(len(hb.SERVICE_DEFS), 18)
        ids = [row[0] for row in hb.SERVICE_DEFS]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertIn("cloudbase", ids)
        self.assertEqual(len(hb.CLOUD_OWNED_IDS), 8)


if __name__ == "__main__":
    unittest.main(verbosity=2)
