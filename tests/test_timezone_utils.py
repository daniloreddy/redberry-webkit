from __future__ import annotations

from zoneinfo import ZoneInfo

from redberry_webkit.timezone_utils import resolve_timezone


def test_resolve_timezone_utc() -> None:
    assert resolve_timezone("UTC") == ZoneInfo("UTC")


def test_resolve_timezone_valid_iana_name() -> None:
    assert resolve_timezone("Europe/Rome") == ZoneInfo("Europe/Rome")


def test_resolve_timezone_invalid_falls_back_to_utc() -> None:
    assert resolve_timezone("Not/AZone") == ZoneInfo("UTC")


def test_resolve_timezone_empty_string_falls_back_to_utc() -> None:
    # ZoneInfo("") raises ValueError, not ZoneInfoNotFoundError — a TZ="" in .env must
    # not crash the app at import time (app/ui/pages.py.jinja's module-level DISPLAY_TZ).
    assert resolve_timezone("") == ZoneInfo("UTC")


def test_resolve_timezone_path_like_value_falls_back_to_utc() -> None:
    # Also raises ValueError, not ZoneInfoNotFoundError.
    assert resolve_timezone("../../etc/passwd") == ZoneInfo("UTC")
