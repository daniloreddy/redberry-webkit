from __future__ import annotations

import time
from pathlib import Path

from redberry_webkit.metrics import MetricsRecord, MetricsStore


async def test_init_db_creates_file(tmp_path: Path) -> None:
    db_path = tmp_path / "metrics.db"
    store = MetricsStore(db_path=db_path)
    await store.init_db()
    assert db_path.exists()


async def test_record_and_get_history(tmp_path: Path) -> None:
    store = MetricsStore(db_path=tmp_path / "metrics.db")
    await store.init_db()
    await store.record(MetricsRecord(timestamp=time.time(), status="ok", duration_s=1.5))
    await store.record(MetricsRecord(timestamp=time.time(), status="error", duration_s=0.5, error_message="boom"))

    history = await store.get_history()
    assert len(history) == 2
    assert history[0].status == "error"
    assert history[0].error_message == "boom"
    assert history[1].status == "ok"


async def test_get_history_respects_limit_and_order(tmp_path: Path) -> None:
    store = MetricsStore(db_path=tmp_path / "metrics.db")
    await store.init_db()
    base = time.time()
    for i in range(5):
        await store.record(MetricsRecord(timestamp=base + i, status="ok", duration_s=1.0))

    history = await store.get_history(limit=2)
    assert len(history) == 2
    assert history[0].timestamp > history[1].timestamp


async def test_record_with_extra_roundtrips_json(tmp_path: Path) -> None:
    store = MetricsStore(db_path=tmp_path / "metrics.db")
    await store.init_db()
    await store.record(
        MetricsRecord(timestamp=time.time(), status="ok", duration_s=2.0, extra={"model": "sonnet", "tokens": 42})
    )
    history = await store.get_history()
    assert history[0].extra == {"model": "sonnet", "tokens": 42}


async def test_record_without_extra_is_none(tmp_path: Path) -> None:
    store = MetricsStore(db_path=tmp_path / "metrics.db")
    await store.init_db()
    await store.record(MetricsRecord(timestamp=time.time(), status="ok", duration_s=1.0))
    history = await store.get_history()
    assert history[0].extra is None


async def test_get_stats_counts_and_averages(tmp_path: Path) -> None:
    store = MetricsStore(db_path=tmp_path / "metrics.db")
    await store.init_db()
    now = time.time()
    await store.record(MetricsRecord(timestamp=now, status="ok", duration_s=2.0))
    await store.record(MetricsRecord(timestamp=now, status="ok", duration_s=4.0))
    await store.record(MetricsRecord(timestamp=now, status="error", duration_s=1.0, error_message="x"))

    stats = await store.get_stats()
    assert stats["total_requests"] == 3
    assert stats["ok_requests"] == 2
    assert stats["error_requests"] == 1
    assert stats["avg_duration_s"] == (2.0 + 4.0 + 1.0) / 3


async def test_get_stats_excludes_records_outside_window(tmp_path: Path) -> None:
    store = MetricsStore(db_path=tmp_path / "metrics.db")
    await store.init_db()
    old_timestamp = time.time() - 48 * 3600
    await store.record(MetricsRecord(timestamp=old_timestamp, status="ok", duration_s=1.0))

    stats = await store.get_stats(hours=24)
    assert stats["total_requests"] == 0


async def test_get_stats_empty_db_returns_zeros(tmp_path: Path) -> None:
    store = MetricsStore(db_path=tmp_path / "metrics.db")
    await store.init_db()
    stats = await store.get_stats()
    assert stats == {"total_requests": 0, "ok_requests": 0, "error_requests": 0, "avg_duration_s": 0.0}


async def test_purge_old_removes_stale_records(tmp_path: Path) -> None:
    store = MetricsStore(db_path=tmp_path / "metrics.db")
    await store.init_db()
    old_timestamp = time.time() - 40 * 86400
    recent_timestamp = time.time()
    await store.record(MetricsRecord(timestamp=old_timestamp, status="ok", duration_s=1.0))
    await store.record(MetricsRecord(timestamp=recent_timestamp, status="ok", duration_s=1.0))

    await store.purge_old(days=30)

    history = await store.get_history()
    assert len(history) == 1
    assert history[0].timestamp == recent_timestamp
