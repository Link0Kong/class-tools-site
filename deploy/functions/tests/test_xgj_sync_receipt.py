import importlib.util
import time
from pathlib import Path
from unittest import mock


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


FUNCTIONS = Path(__file__).resolve().parents[1]
sync = load("xgj_sync_test_target", FUNCTIONS / "xgj_sync" / "index.py")
probe = load("health_probe_xgj_test_target", FUNCTIONS / "health_probe" / "health_beat.py")


def test_job_heartbeat_covers_no_new_homework_and_write_failure():
    replies = iter([(200, []), (200, []), (201, None)])
    with mock.patch.object(sync, "_http", side_effect=lambda *a, **k: next(replies)) as http:
        result = sync._run("base", "key", "test-credential", lambda: {"items": []}, "cloudbase")
    assert result["ok"] and result["pending"] == 0
    args = http.call_args.args
    assert args[2] == "site_assets?on_conflict=id"
    receipt = args[3][0]
    assert receipt["id"] == "xgj-sync-status"
    assert receipt["body"]["ok"] and receipt["body"]["pending"] == 0

    payload = {"items": [{"key": "xgj_en_sample", "status": "未完成", "ts": 100}]}
    replies = iter([(200, [{"id": "auto_hw_xgj_en_old", "archived": False}]), (500, None), (201, None)])
    with mock.patch.object(sync, "_http", side_effect=lambda *a, **k: next(replies)) as http:
        result = sync._run("base", "key", "test-credential", lambda: payload, "local")
    assert result["ok"] is False and result["error_code"] == "write_failed"
    assert all(call.args[4] != "PATCH" for call in http.call_args_list if len(call.args) > 4)
    assert http.call_args.args[3][0]["id"] == "xgj-sync-status-local"


def test_report_health_uses_job_time_and_ignores_assignment_age():
    old = int((time.time() - 44 * 3600) * 1000)
    with mock.patch.object(probe, "_cb_request", side_effect=[(200, [], 1), (200, [{"ts": old}], 1)]):
        row = probe.detect_cloud_xgj_sync("base", "key", "test-credential")
    assert row["status"] == "unknown" and "发布于" in row["detail"]

    now = int(time.time() * 1000)
    cloud = {"id": "xgj-sync-status", "body": {"at_ms": now, "runner": "cloudbase", "ok": True, "pending": 0}}
    local = {"id": "xgj-sync-status-local", "body": {"at_ms": now, "runner": "local", "ok": True}}
    with mock.patch.object(probe, "_cb_request", return_value=(200, [cloud], 1)) as http:
        row = probe.detect_cloud_xgj_sync("base", "key", "test-credential")
    assert http.call_count == 1 and row["status"] == "ok" and "暂无待同步作业" in row["detail"]

    cloud["body"]["ok"] = False
    with mock.patch.object(probe, "_cb_request", return_value=(200, [cloud, local], 1)):
        row = probe.detect_cloud_xgj_sync("base", "key", "test-credential")
    assert row["status"] == "warn" and row["meta"]["fallback"]["ok"]
