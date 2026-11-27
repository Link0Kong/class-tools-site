import copy
import json
import sys
import threading
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import home_context_app as app

NOW = datetime(2026, 11, 27, 3, tzinfo=timezone.utc)
PAGES = {
    "EVERYDAY": ("日常观察", "https://itp.cas.cn/cbkx/kpwz/"),
    "STUDY": ("学习方法", "https://lsc.cornell.edu/how-to-study/"),
}
LINES = (
    "翻书页时也给窗外留一眼。",
    "等车的片刻可以听听风声。",
    "回去的路可以换个步调。",
    "书桌有角落，散步也有。",
    "把零碎的念头夹进书签。",
    "水杯和便签今天同桌。",
    "用自己的话复述一个概念。",
    "给刚学的内容画一张小图。",
    "给手边的笔记留一个提问。",
    "先画出第一个观察到的变化。",
    "让昨天的摘记回来串个门。",
    "几个关键词也能约好碰面。",
)


def generated_entries():
    return [{"text": text, "topic": topic, "tone": tone, "sourceId": topic.lower()}
            for topic, offset in (("EVERYDAY", 0), ("STUDY", 6))
            for i, text in enumerate(LINES[offset:offset + 6])
            for tone in (app.TONES[i // 2],)]


def sender(calls, entries=None):
    def send(url, payload, **kwargs):
        calls.append((url, payload))
        if url == app.SEARCH_URL:
            topic = "STUDY" if "cornell" in payload["query"] else "EVERYDAY"
            title, site = PAGES[topic]
            return {"results": [{"title": title, "url": site}]}
        if url == app.FETCH_URL:
            return {"title": "测试素材 - Skip to main content", "content": "Page excerpt about reading and everyday science. " * 10}
        assert url == app.DEEPSEEK_URL
        if payload.get("safety_check"):
            return {"choices": [{"finish_reason": "stop", "message": {"content": json.dumps({"accepted": list(range(1, 13))})}}]}
        return {"choices": [{"finish_reason": "stop",
                             "message": {"content": json.dumps({"entries": entries or generated_entries()})}}]}
    return send


def test_daily_public_material_only_atomic_validated_output_and_attempt_limit(tmp_path):
    calls = []
    assert app.generate_daily(tmp_path, NOW, sender(calls)) == "published"
    assert app.generate_daily(tmp_path, NOW, sender(calls)) == "already_attempted"
    assert [url for url, _ in calls] == [app.SEARCH_URL, app.FETCH_URL, app.SEARCH_URL, app.FETCH_URL, app.DEEPSEEK_URL, app.DEEPSEEK_URL]
    assert all(set(payload) == {"query", "count", "need_content"}
               for url, payload in calls if url == app.SEARCH_URL)
    request = calls[-2][1]
    assert request["model"] == "deepseek-flash"
    assert request["response_format"] == {"type": "json_object"}
    assert calls[-1][1]["safety_check"] == {"level": "high"}
    assert "response_format" not in calls[-1][1]
    assert "sourceId" in request["messages"][1]["content"]

    batch = app.read_batch(tmp_path / "content.json", NOW)
    assert len(batch["entries"]) == len({row["id"] for row in batch["entries"]}) == 12
    assert {row["sourceTitle"] for row in batch["entries"]} == {"测试素材"}
    assert app.read_batch(tmp_path / "content.json", NOW + timedelta(hours=72)) is None
    assert app.read_batch(tmp_path / "content.json", NOW - timedelta(seconds=1)) is None
    assert app.generate_daily(tmp_path, NOW + timedelta(days=1), sender(calls)) == "published"
    assert app.read_batch(tmp_path / "content.json", NOW + timedelta(days=1))["entries"] == batch["entries"]


@pytest.mark.parametrize("invalid", ["duplicate", "source_swap", "refused", "review_rejects", "unavailable", "no_search_match", "untrusted_url"])
def test_invalid_day_retains_previous_batch(tmp_path, invalid):
    app.generate_daily(tmp_path, NOW, sender([]))
    path = tmp_path / "content.json"
    previous = path.read_bytes()
    entries = copy.deepcopy(generated_entries())
    if invalid == "duplicate":
        entries[0]["text"] = entries[1]["text"]
    if invalid == "source_swap":
        entries[0]["sourceId"] = "study"

    def send(url, payload, **kwargs):
        if invalid == "refused" and url == app.DEEPSEEK_URL:
            return {"choices": [{"finish_reason": "content_filter"}]}
        if invalid == "review_rejects" and payload.get("safety_check"):
            return {"choices": [{"finish_reason": "stop", "message": {"content": '{"accepted":[]}'}}]}
        if invalid == "unavailable":
            raise OSError("network unavailable")
        if invalid == "no_search_match":
            return {"results": []}
        if invalid == "untrusted_url":
            return {"results": [{"title": "spoof", "url": "https://cas.cn.invalid/"}]}
        return sender([], entries)(url, payload, **kwargs)

    with pytest.raises((ValueError, OSError)):
        app.generate_daily(tmp_path, NOW + timedelta(days=1), send)
    assert path.read_bytes() == previous
    assert app.generate_daily(tmp_path, NOW + timedelta(days=1), send) == "already_attempted"


def test_weather_timestamp_regions_dedup_and_astronomy(tmp_path):
    calls = []
    hits = 0

    def fetch(path):
        nonlocal hits
        calls.append(path)
        if path.startswith("/v7/astronomy/sun"):
            return {"code": "200", "sunrise": "2026-11-27T06:30:00+08:00",
                    "sunset": "2026-11-27T17:10:00+08:00", "refer": {"sources": ["Test attribution"]}}
        hits += 1
        stamp = NOW if hits < 3 else NOW - timedelta(hours=1)
        return {"validTime": stamp.isoformat(), "condition": {"code": "100", "text": "晴"},
                "temperature": {"value": 20, "unit": "°C"}}

    regions = app.read_regions(None)
    regions["123"] = (31.2, 121.3)
    weather = app.WeatherAdapter(regions, fetch)
    value = weather.get("minhou", NOW)
    assert value["regionId"] == "minhou" and value["sunset"] and value["temperatureC"] == 20
    assert calls[0].startswith("/weather/v1/current/26.15/119.15")
    assert weather.get("minhou", NOW + timedelta(minutes=14)) == value
    assert len(calls) == 2
    assert weather.get("123", NOW)["regionId"] == "123"
    assert weather.get("minhou", NOW + timedelta(minutes=45)) is None

    app.generate_daily(tmp_path, NOW, sender([]))
    with app.HomeContextServer(("127.0.0.1", 0), tmp_path / "content.json", weather, lambda: NOW) as server:
        worker = threading.Thread(target=server.serve_forever)
        worker.start()
        try:
            base = "http://127.0.0.1:" + str(server.server_port)
            with urllib.request.urlopen(base + app.CONTENT_PATH, timeout=3) as response:
                assert len(json.load(response)["entries"]) == 12
            with pytest.raises(urllib.error.HTTPError) as exc:
                urllib.request.urlopen(base + app.WEATHER_PATH + "?region=unknown", timeout=3)
            assert exc.value.code == 400
            exc.value.close()
        finally:
            server.shutdown()
            worker.join()
