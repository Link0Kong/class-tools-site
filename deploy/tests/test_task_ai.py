"""Local task AI checks. Both external services are stubbed."""

import base64
import gzip
import json
import sys
import threading
import urllib.error
import urllib.request
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import ecs_site
import ecs_task_ai
import task_ai_app as ai


INPUT = {"text": "明天下午5点前交实验报告。另：取新的实验器材。", "localDate": "2026-11-26"}
MODEL_OUTPUT = {"drafts": [
    {"title": "提交实验报告", "notes": "明天下午提交", "due": "2026-11-27",
     "dueTime": "17:00", "deadlineText": "明天下午5点前",
     "steps": [{"text": " 检查数据 ", "note": "核对单位"}, {"text": "检查数据"}],
     "suggestions": ["先核对格式", "", "先核对格式"]},
    {"title": "取实验器材"},
]}


@pytest.fixture
def external(monkeypatch):
    calls = []

    def stub(url, payload, headers, *_):
        calls.append((url, payload, headers))
        if url == ai.WHOAMI_URL:
            return {"ok": True, "sid": "9999000001"} if headers["X-Device-Id"] == "test-token" else {"ok": False}
        assert url == ai.DEEPSEEK_URL
        return {"choices": [{"finish_reason": "stop", "message": {"content": json.dumps(MODEL_OUTPUT)}}]}

    monkeypatch.setattr(ai, "post_json", stub)
    return calls


@pytest.fixture
def server():
    with ai.TaskAiServer(("127.0.0.1", 0), "test-publish-key", "test-model-key") as server:
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            yield server
        finally:
            server.shutdown()
            thread.join()


def request(server, payload=INPUT, header="X-Class-Token", token="test-token", path=ai.SUGGEST_PATH):
    headers = {"Content-Type": "application/json"}
    if header:
        headers[header] = token
    url = "http://127.0.0.1:%d%s" % (server.server_address[1], path)
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=body, headers=headers)
    try:
        response = urllib.request.urlopen(req, timeout=2)
    except urllib.error.HTTPError as exc:
        response = exc
    with response:
        return response.code, json.loads(response.read()), response.headers


@pytest.mark.parametrize("header", ["X-Class-Token", "X-Device-Id"])
def test_suggestion_and_data_minimization(server, external, header):
    status, payload, headers = request(server, header=header)
    assert status == 200
    assert headers["Cache-Control"] == "no-store"
    assert payload == {"drafts": [
        {"title": "提交实验报告", "notes": "明天下午提交", "due": "2026-11-27", "dueTime": "17:00",
         "steps": [{"text": "检查数据", "note": "核对单位"}], "suggestions": ["先核对格式"]},
        {"title": "取实验器材", "notes": "", "due": "", "dueTime": "", "steps": [], "suggestions": []},
    ]}
    (_, auth_payload, auth_headers), (_, model_payload, model_headers) = external
    assert auth_payload == {} and auth_headers["X-Device-Id"] == "test-token"
    assert json.loads(model_payload["messages"][1]["content"]) == INPUT
    assert model_payload["response_format"] == {"type": "json_object"}
    assert model_payload["thinking"] == {"type": "disabled"}
    assert model_headers == {"Authorization": "Bearer test-model-key"}


@pytest.mark.parametrize("bad_input", [
    [], {"text": "", "localDate": "2026-11-26"}, {"text": "a" * 6001, "localDate": "2026-11-26"},
    {"text": 123, "localDate": "2026-11-26"}, {"text": "ok", "localDate": "2026-02-29"},
    {"text": "ok", "localDate": "20261126"},
])
def test_invalid_input_does_not_contact_services(server, external, bad_input):
    assert request(server, bad_input)[:2] == (400, {"error": "invalid_request"})
    assert external == []


def test_missing_and_invalid_identity_never_call_model(server, external):
    assert request(server, header=None)[:2] == (401, {"error": "unauthorized"})
    assert request(server, token="invalid")[:2] == (401, {"error": "unauthorized"})
    assert [call[0] for call in external] == [ai.WHOAMI_URL]


def test_no_secret_returns_service_unavailable(server, external):
    server.model_key = ""
    assert request(server)[:2] == (503, {"error": "ai_unavailable"})
    assert external == []


def test_valid_input_at_character_limit(server, external):
    text = "任" * 5999 + "🚀"
    status, _, _ = request(server, {**INPUT, "text": text})
    assert status == 200
    assert json.loads(external[-1][1]["messages"][1]["content"])["text"] == text


def test_rate_limit_is_per_verified_account(server, external):
    for _ in range(6):
        assert request(server)[0] == 200
    assert request(server)[:2] == (429, {"error": "rate_limited"})
    assert sum(call[0] == ai.DEEPSEEK_URL for call in external) == 6


def test_model_busy_returns_rate_limit_without_spending_quota(server, external):
    for _ in range(4):
        assert server.model_slots.acquire(blocking=False)
    assert request(server)[:2] == (429, {"error": "rate_limited"})
    assert [call[0] for call in external] == [ai.WHOAMI_URL]
    assert not server.account_limits.requests


@pytest.mark.parametrize("deadline, output_due, output_time, expected", [
    ("明天", "2026-11-27", "17:00", ("2026-11-27", "")),
    ("稍后", "2026-11-27", "17:00", ("", "")),
    ("11月29日晚8点", "2026-11-29", "20:00", ("", "")),
    ("明天下午5点前", "2026-02-29", "17:00", ("", "")),
    ("明天下午5点前", "2026-11-27", "25:00", ("2026-11-27", "")),
])
def test_dates_and_times_require_valid_values_and_explicit_source(deadline, output_due, output_time, expected):
    row = {"title": "报告", "due": output_due, "dueTime": output_time, "deadlineText": deadline}
    draft = ai.normalize_result({"drafts": [row]}, INPUT["text"] + "稍后打开教室")["drafts"][0]
    assert (draft["due"], draft["dueTime"]) == expected


def test_draft_limits_and_empty_vs_bad_result():
    steps = [{"text": "步骤 %s\n" % index, "note": "长" * 510} for index in range(20)]
    row = {"title": "长" * 210, "notes": "长" * 1610, "steps": steps, "suggestions": list("abcdef")}
    result = ai.normalize_result({"drafts": [row] * 10}, "")
    assert len(result["drafts"]) == 8
    first = result["drafts"][0]
    assert len(first["title"]) == 200 and len(first["notes"]) == 1600
    assert len(first["steps"]) == 12 and len(first["steps"][0]["note"]) == 500
    assert first["suggestions"] == list("abc")
    assert ai.normalize_result({"drafts": []}, "") == {"drafts": []}
    with pytest.raises(ai.ApiError) as exc:
        ai.normalize_result({"drafts": [{"title": ""}]}, "")
    assert exc.value.status == 502


@pytest.mark.parametrize("model_issue, expected", [
    (TimeoutError("upstream detail"), (504, {"error": "ai_timeout"})),
    (OSError("upstream detail"), (503, {"error": "ai_unavailable"})),
    ({"choices": [{"finish_reason": "length"}]}, (502, {"error": "invalid_response"})),
    ({"choices": [{"finish_reason": "stop", "message": {"content": "  "}}]}, (502, {"error": "invalid_response"})),
])
def test_model_errors_are_safe_and_typed(server, monkeypatch, model_issue, expected):
    def stub(url, *_):
        if url == ai.WHOAMI_URL:
            return {"ok": True, "sid": "9999000001"}
        if isinstance(model_issue, Exception):
            raise model_issue
        return model_issue

    monkeypatch.setattr(ai, "post_json", stub)
    assert request(server)[:2] == expected


def test_failed_auth_gateway_is_not_reported_as_invalid_identity(server, monkeypatch):
    def unavailable(url, *_):
        assert url == ai.WHOAMI_URL
        raise TimeoutError("unavailable")

    monkeypatch.setattr(ai, "post_json", unavailable)
    assert request(server)[:2] == (503, {"error": "identity_unavailable"})


def test_deploy_package_and_https_route():
    script = ecs_task_ai.install_script()
    chunk = script.split(" | base64 -d", 1)[0].rsplit("'", 2)[1]
    assert gzip.decompress(base64.b64decode(chunk)) == ecs_task_ai.APP.read_bytes()
    assert len(base64.b64encode(script.encode("utf-8"))) < 16 * 1024
    assert ecs_site._caddy_https().count(ai.SUGGEST_PATH) == 1
    assert ai.SUGGEST_PATH not in ecs_site._caddy_http()
    assert repr(ecs_site.TASK_AI_ROUTE) in ecs_task_ai.route_script()
    assert "__TASK_AI_ROUTE__" not in ecs_site._caddy_https()
