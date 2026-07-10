from __future__ import annotations

from zoneinfo import ZoneInfo

from redberry_webkit.timezone_utils import resolve_timezone


def test_resolve_timezone_utc() -> None:
    assert resolve_timezone("UTC") == ZoneInfo("UTC")


def test_resolve_timezone_valid_iana_name() -> None:
    assert resolve_timezone("Europe/Rome") == ZoneInfo("Europe/Rome")


def test_resolve_timezone_invalid_falls_back_to_utc() -> None:
    assert resolve_timezone("Not/AZone") == ZoneInfo("UTC")
