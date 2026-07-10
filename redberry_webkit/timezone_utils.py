from __future__ import annotations

import logging
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

logger = logging.getLogger(__name__)


def resolve_timezone(tz_name: str) -> ZoneInfo:
    """Resolve tz_name to a ZoneInfo, falling back to UTC (with a logged warning) if unknown."""
    try:
        return ZoneInfo(tz_name)
    except ZoneInfoNotFoundError:
        logger.warning("unknown TZ %r, falling back to UTC", tz_name)
        return ZoneInfo("UTC")
