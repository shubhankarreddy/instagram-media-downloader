from __future__ import annotations

import importlib.util
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest


MODULE_PATH = Path(__file__).resolve().parents[1] / "insta_downloader.py"
SPEC = importlib.util.spec_from_file_location("insta_downloader", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC is not None and SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class _FakeResponse:
    def __init__(self, status_code: int, text: str, payload: Any = None, json_raises: bool = False) -> None:
        self.status_code = status_code
        self.text = text
        self._payload = payload
        self._json_raises = json_raises

    def json(self) -> Any:
        if self._json_raises:
            raise ValueError("bad json")
        return self._payload


class _FakeSession:
    def __init__(self, response: _FakeResponse | None = None, request_error: Exception | None = None) -> None:
        self._response = response
        self._request_error = request_error

    def request(self, method: str, url: str, timeout: int, **kwargs: Any) -> _FakeResponse:
        if self._request_error:
            raise self._request_error
        assert method
        assert url
        assert timeout > 0
        assert self._response is not None
        return self._response


def test_sanitize_username_from_valid_url() -> None:
    assert MODULE.sanitize_username("https://www.instagram.com/some_username/") == "some_username"


def test_sanitize_username_rejects_reserved_path() -> None:
    with pytest.raises(SystemExit, match="Input looks like an Instagram path"):
        MODULE.sanitize_username("https://www.instagram.com/reels/")


def test_sanitize_username_rejects_non_instagram_domain() -> None:
    with pytest.raises(SystemExit, match="URL must point to instagram.com"):
        MODULE.sanitize_username("https://example.com/some_username/")


def test_pick_highest_quality_prefers_largest_resolution() -> None:
    candidates = [
        {"url": "https://cdn.example/low.jpg", "width": 320, "height": 240},
        {"url": "https://cdn.example/high.jpg", "width": 1920, "height": 1080},
        {"url": "https://cdn.example/medium.jpg", "width": 1280, "height": 720},
    ]
    assert MODULE.pick_highest_quality(candidates) == "https://cdn.example/high.jpg"


def test_pick_highest_quality_ignores_invalid_candidates() -> None:
    candidates = [
        {"width": 100, "height": 100},
        "not-a-dict",
        {"url": "https://cdn.example/fallback.jpg"},
    ]
    assert MODULE.pick_highest_quality(candidates) == "https://cdn.example/fallback.jpg"


def test_build_existing_code_index_reads_stamped_and_legacy_files(tmp_path: Path) -> None:
    (tmp_path / "20260101_020304_ABC123.jpg").write_text("x", encoding="utf-8")
    (tmp_path / "DEF456.mp4").write_text("x", encoding="utf-8")
    (tmp_path / "not_media_name.txt").write_text("x", encoding="utf-8")

    without_legacy = MODULE.build_existing_code_index(tmp_path, include_legacy_reels=False)
    with_legacy = MODULE.build_existing_code_index(tmp_path, include_legacy_reels=True)

    assert without_legacy == {"ABC123"}
    assert with_legacy == {"ABC123", "DEF456"}


def test_positive_int_validation() -> None:
    assert MODULE.positive_int("5") == 5
    with pytest.raises(Exception):
        MODULE.positive_int("0")


def test_normalize_end_of_day_sets_time_bounds() -> None:
    source = datetime(2026, 4, 26, tzinfo=timezone.utc)
    result = MODULE.normalize_end_of_day(source)
    assert result is not None
    assert result.hour == 23
    assert result.minute == 59
    assert result.second == 59
    assert result.microsecond == 999999


def test_is_within_date_range_handles_boundaries() -> None:
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    end = MODULE.normalize_end_of_day(datetime(2026, 1, 31, tzinfo=timezone.utc))

    inside_ts = int(datetime(2026, 1, 15, tzinfo=timezone.utc).timestamp())
    before_ts = int(datetime(2025, 12, 31, 23, 59, tzinfo=timezone.utc).timestamp())
    after_ts = int(datetime(2026, 2, 1, tzinfo=timezone.utc).timestamp())

    assert MODULE.is_within_date_range(inside_ts, start, end)
    assert not MODULE.is_within_date_range(before_ts, start, end)
    assert not MODULE.is_within_date_range(after_ts, start, end)


def test_request_json_success_path() -> None:
    session = _FakeSession(response=_FakeResponse(200, "ok", payload={"a": 1}))
    result = MODULE.request_json(
        session,
        "GET",
        "https://example.test/api",
        timeout=5,
        context="Test request",
    )
    assert result == {"a": 1}


def test_request_json_fail_fast_on_http_error() -> None:
    session = _FakeSession(response=_FakeResponse(429, "rate limited", payload={}))
    with pytest.raises(SystemExit, match="HTTP 429"):
        MODULE.request_json(
            session,
            "GET",
            "https://example.test/api",
            timeout=5,
            context="Test request",
        )


def test_request_json_fail_fast_on_non_json() -> None:
    session = _FakeSession(
        response=_FakeResponse(200, "<html>challenge</html>", payload=None, json_raises=True)
    )
    with pytest.raises(SystemExit, match="non-JSON"):
        MODULE.request_json(
            session,
            "GET",
            "https://example.test/api",
            timeout=5,
            context="Test request",
        )


def test_request_json_fail_fast_on_network_error() -> None:
    session = _FakeSession(request_error=MODULE.requests.RequestException("boom"))
    with pytest.raises(SystemExit, match="network error"):
        MODULE.request_json(
            session,
            "GET",
            "https://example.test/api",
            timeout=5,
            context="Test request",
        )


def test_iter_image_urls_uses_highest_quality(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = {
        "items": [
            {
                "product_type": "feed",
                "code": "IMG001",
                "taken_at": 1700000000,
                "image_versions2": {
                    "candidates": [
                        {"url": "https://cdn.example/low.jpg", "width": 320, "height": 240},
                        {"url": "https://cdn.example/high.jpg", "width": 1920, "height": 1080},
                    ]
                },
            }
        ],
        "more_available": False,
    }

    monkeypatch.setattr(MODULE, "request_json", lambda *args, **kwargs: payload)

    class _Session:
        pass

    urls = list(MODULE.iter_image_urls(_Session(), "123"))
    assert urls == [("IMG001", "https://cdn.example/high.jpg", 1700000000)]


def test_iter_reel_urls_uses_highest_quality(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = {
        "items": [
            {
                "media": {
                    "product_type": "clips",
                    "code": "REEL001",
                    "taken_at": 1700000001,
                    "video_versions": [
                        {"url": "https://cdn.example/low.mp4", "width": 640, "height": 360},
                        {"url": "https://cdn.example/high.mp4", "width": 1920, "height": 1080},
                    ],
                }
            }
        ],
        "paging_info": {"more_available": False},
    }

    monkeypatch.setattr(MODULE, "request_json", lambda *args, **kwargs: payload)

    class _Cookies(dict):
        def get(self, key: str, default: str = "") -> str:
            return super().get(key, default)

    class _Session:
        def __init__(self) -> None:
            self.cookies = _Cookies()
            self.headers: dict[str, str] = {}

    urls = list(MODULE.iter_reel_video_urls(_Session(), "456"))
    assert urls == [("REEL001", "https://cdn.example/high.mp4", 1700000001)]
