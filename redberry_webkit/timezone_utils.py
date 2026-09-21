from __future__ import annotations

import logging
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

logger = logging.getLogger(__name__)


def resolve_timezone(tz_name: str) -> ZoneInfo:
    """Resolve tz_name to a ZoneInfo, falling back to UTC (with a logged warning) if unknown."""
    try:
        return ZoneInfo(tz_name)
    except (ZoneInfoNotFoundError, ValueError):
        # ZoneInfoNotFoundError covers a well-formed but unrecognized key (e.g. "Foo/Bar").
        # ValueError covers a malformed one — "" or a path-like value ("../../etc/passwd")
        # raise ValueError instead ("ZoneInfo keys must be normalized relative paths" /
        # "...must refer to subdirectories of TZPATH"), confirmed directly against
        # zoneinfo. Without this, an invalid TZ env var crashes the app at import time
        # (this is called at module load, see app/ui/pages.py.jinja's DISPLAY_TZ) instead
        # of falling back — violates the project's own "TZ invalid -> UTC, never crash" rule.
        logger.warning("unknown TZ %r, falling back to UTC", tz_name)
        return ZoneInfo("UTC")
