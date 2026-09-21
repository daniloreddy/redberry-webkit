from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

from .auth import client_ip
from .metrics import MetricsRecord

REQUEST_TABLE_BASE_COLUMNS: list[dict[str, str]] = [
    {"name": "timestamp", "label": "Quando", "field": "timestamp"},
    {"name": "ip", "label": "IP", "field": "ip"},
    {"name": "duration_s", "label": "Durata (s)", "field": "duration_s"},
    {"name": "status", "label": "Stato", "field": "status"},
    {"name": "user_agent", "label": "User Agent", "field": "user_agent"},
]
"""Column defs shared across projects (web-go.md §7 column set, minus app-specific
fields). A project's `ui.table(columns=...)` inserts its own app-specific column dicts
between "ip" and "duration_s" — same order as the Go dashboards."""

STATUS_CELL_SLOT = """
<q-td :props="props">
  <q-badge
    :color="props.value === 'ok' ? 'positive' : 'negative'"
    :label="props.value"
  />
</q-td>
"""
"""Vue slot for `tbl.add_slot("body-cell-status", STATUS_CELL_SLOT)` — identical string
previously hand-duplicated in mid_service_py and mailmanager."""


@dataclass
class RequestRow:
    """View-model for one row of a request-history table. Project code embeds this
    (or copies its fields) alongside its own app-specific columns — same pattern as
    Go's `app.RequestRow`."""

    id: str
    timestamp: str
    ip: str
    status: str
    duration_s: str
    user_agent: str
    error_message: str
    extra: dict[str, object]


def request_meta(headers: Mapping[str, str], client_host: str, trusted_proxies: set[str]) -> tuple[str, str]:
    """Resolve (ip, user_agent) from a request for passing into `metrics.record(extra=...)`.

    IP resolution delegates to `auth.client_ip()` — same trusted-proxy logic used for
    login brute-force blocking, not reimplemented here. `headers` keys must be lowercase
    (e.g. `dict(request.headers)` from FastAPI/Starlette, whose `Headers` already
    normalizes to lowercase on iteration).
    """
    return client_ip(headers, client_host, trusted_proxies), headers.get("user-agent", "")


def request_rows_from_metrics(records: list[MetricsRecord], tz: ZoneInfo) -> list[RequestRow]:
    """Build `RequestRow`s from `MetricsStore.get_history()` output.

    `ip`/`user_agent` come from `extra["client_ip"]`/`extra["user_agent"]` — the
    escape-hatch fields `metrics.record()` doesn't have native columns for yet. A record
    predating this convention (or written by a project not yet passing them) simply
    renders as an empty string, same fallback Go webkit uses for pre-0.3.0 records.
    """
    rows: list[RequestRow] = []
    for index, record in enumerate(records):
        extra = record.extra or {}
        rows.append(
            RequestRow(
                id=str(index),
                timestamp=datetime.fromtimestamp(record.timestamp, tz=tz).strftime("%Y-%m-%d %H:%M:%S"),
                ip=str(extra.get("client_ip", "")),
                status=record.status,
                duration_s=f"{record.duration_s:.2f}",
                user_agent=str(extra.get("user_agent", "")),
                error_message=record.error_message or "",
                extra=extra,
            )
        )
    return rows
