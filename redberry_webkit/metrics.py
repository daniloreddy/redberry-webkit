from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import aiosqlite

logger = logging.getLogger(__name__)

_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS requests (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp      REAL    NOT NULL,
    status         TEXT    NOT NULL,
    duration_s     REAL    NOT NULL,
    error_message  TEXT,
    extra          TEXT
)
"""


@dataclass
class MetricsRecord:
    timestamp: float
    status: Literal["ok", "error"]
    duration_s: float
    error_message: str | None = None
    extra: dict[str, Any] | None = None


class MetricsStore:
    """Async SQLite request-metrics store: init, record, aggregate stats, history, retention purge.

    Not a class-level singleton: instantiate once per project, typically as a
    module-level `metrics = MetricsStore(db_path=...)` in the app's own metrics.py,
    and import that instance everywhere — same convention as AuthManager/ConfigManager.
    `extra` is a free-form JSON escape hatch for project-specific fields (token counts,
    URLs, model names, ...) so the schema stays generic across projects.
    """

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self._lock = asyncio.Lock()

    async def init_db(self) -> None:
        """Create the requests table if missing. Call once at app startup."""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(_CREATE_TABLE_SQL)
            await db.commit()

    async def record(self, rec: MetricsRecord) -> None:
        """Persist one request record."""
        extra_json = json.dumps(rec.extra) if rec.extra is not None else None
        async with self._lock, aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "INSERT INTO requests (timestamp, status, duration_s, error_message, extra) "
                "VALUES (?, ?, ?, ?, ?)",
                (rec.timestamp, rec.status, rec.duration_s, rec.error_message, extra_json),
            )
            await db.commit()

    async def get_stats(self, hours: int = 24) -> dict[str, Any]:
        """Aggregate counts/durations for requests within the last `hours`."""
        since = time.time() - hours * 3600
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute(
                "SELECT COUNT(*), "
                "SUM(CASE WHEN status = 'ok' THEN 1 ELSE 0 END), "
                "SUM(CASE WHEN status = 'error' THEN 1 ELSE 0 END), "
                "AVG(duration_s) "
                "FROM requests WHERE timestamp >= ?",
                (since,),
            ) as cursor:
                row = await cursor.fetchone()
        total, ok, errors, avg_duration = row if row else (0, 0, 0, None)
        return {
            "total_requests": total or 0,
            "ok_requests": ok or 0,
            "error_requests": errors or 0,
            "avg_duration_s": avg_duration or 0.0,
        }

    async def get_history(self, limit: int = 100) -> list[MetricsRecord]:
        """Return the most recent `limit` records, newest first."""
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute(
                "SELECT timestamp, status, duration_s, error_message, extra "
                "FROM requests ORDER BY timestamp DESC LIMIT ?",
                (limit,),
            ) as cursor:
                rows = await cursor.fetchall()
        return [
            MetricsRecord(
                timestamp=row[0],
                status=row[1],
                duration_s=row[2],
                error_message=row[3],
                extra=json.loads(row[4]) if row[4] is not None else None,
            )
            for row in rows
        ]

    async def purge_old(self, days: int = 30) -> None:
        """Delete records older than `days` — call periodically to bound DB growth."""
        cutoff = time.time() - days * 86400
        async with self._lock, aiosqlite.connect(self.db_path) as db:
            await db.execute("DELETE FROM requests WHERE timestamp < ?", (cutoff,))
            await db.commit()
