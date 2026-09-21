from __future__ import annotations

from zoneinfo import ZoneInfo

from redberry_webkit.metrics import MetricsRecord
from redberry_webkit.request_view import request_meta, request_rows_from_metrics

_UTC = ZoneInfo("UTC")


def test_request_rows_from_metrics_fills_ip_and_user_agent_from_extra() -> None:
    records = [
        MetricsRecord(
            timestamp=1_700_000_000.0,
            status="ok",
            duration_s=0.123,
            extra={"client_ip": "203.0.113.5", "user_agent": "curl/8.0"},
        )
    ]

    rows = request_rows_from_metrics(records, _UTC)

    assert len(rows) == 1
    row = rows[0]
    assert row.id == "0"
    assert row.ip == "203.0.113.5"
    assert row.user_agent == "curl/8.0"
    assert row.status == "ok"
    assert row.duration_s == "0.12"
    assert row.error_message == ""


def test_request_rows_from_metrics_defaults_missing_ip_and_user_agent_to_empty_string() -> None:
    # A record from before this convention existed, or from a project not yet passing
    # client_ip/user_agent — must not KeyError, must render as empty (Go's pre-0.3.0
    # fallback behavior).
    records = [MetricsRecord(timestamp=1_700_000_000.0, status="error", duration_s=1.0, error_message="boom")]

    rows = request_rows_from_metrics(records, _UTC)

    assert rows[0].ip == ""
    assert rows[0].user_agent == ""
    assert rows[0].error_message == "boom"


def test_request_rows_from_metrics_ignores_extra_when_none() -> None:
    records = [MetricsRecord(timestamp=1_700_000_000.0, status="ok", duration_s=0.5, extra=None)]

    rows = request_rows_from_metrics(records, _UTC)

    assert rows[0].ip == ""
    assert rows[0].extra == {}


def test_request_meta_trusts_forwarded_headers_only_from_trusted_proxy() -> None:
    headers = {"x-forwarded-for": "198.51.100.9, 10.0.0.1", "user-agent": "pytest-agent/1.0"}

    ip, ua = request_meta(headers, client_host="127.0.0.1", trusted_proxies={"127.0.0.1"})
    assert ip == "198.51.100.9"
    assert ua == "pytest-agent/1.0"

    # Untrusted client_host: forwarded header ignored, falls back to the raw connection IP.
    ip_untrusted, _ = request_meta(headers, client_host="203.0.113.1", trusted_proxies={"127.0.0.1"})
    assert ip_untrusted == "203.0.113.1"


def test_request_meta_defaults_missing_user_agent_to_empty_string() -> None:
    ip, ua = request_meta({}, client_host="192.0.2.1", trusted_proxies=set())
    assert ip == "192.0.2.1"
    assert ua == ""
