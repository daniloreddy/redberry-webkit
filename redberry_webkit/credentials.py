from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_SECONDS_PER_DAY = 86400

# Default matches Claude Code CLI's ~/.claude/.credentials.json shape — the original
# use case this module was extracted from. Any other CLI tool with a JSON credentials
# file and a millisecond-epoch expiry field passes its own expiry_key_path/filename.
_DEFAULT_EXPIRY_KEY_PATH: tuple[str, ...] = ("claudeAiOauth", "refreshTokenExpiresAt")


@dataclass(frozen=True)
class CredentialsStatus:
    path: Path
    readable: bool
    expires_at_ms: int | None
    checked_at: float

    @property
    def seconds_remaining(self) -> float | None:
        if self.expires_at_ms is None:
            return None
        return self.expires_at_ms / 1000 - self.checked_at

    @property
    def is_expired(self) -> bool:
        remaining = self.seconds_remaining
        return remaining is not None and remaining <= 0

    def is_near_expiry(self, warning_threshold_s: float) -> bool:
        remaining = self.seconds_remaining
        return remaining is not None and 0 < remaining <= warning_threshold_s


def resolve_credentials_path(
    config_dir: str = "", *, default_dir_name: str = ".claude", filename: str = ".credentials.json"
) -> Path:
    base = Path(config_dir) if config_dir.strip() else Path.home() / default_dir_name
    return base / filename


def read_credentials_status(
    path: Path, *, expiry_key_path: Sequence[str] = _DEFAULT_EXPIRY_KEY_PATH
) -> CredentialsStatus:
    now = time.time()
    if not path.exists():
        return CredentialsStatus(path=path, readable=False, expires_at_ms=None, checked_at=now)
    try:
        value: Any = json.loads(path.read_text(encoding="utf-8"))
        for key in expiry_key_path:
            value = value[key]
        return CredentialsStatus(path=path, readable=True, expires_at_ms=int(value), checked_at=now)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        logger.warning("credentials file at %s unreadable or malformed: %s", path, exc)
        return CredentialsStatus(path=path, readable=False, expires_at_ms=None, checked_at=now)


async def watch_loop(
    *,
    path: Path,
    warning_threshold_s: float,
    interval_s: float,
    expiry_key_path: Sequence[str] = _DEFAULT_EXPIRY_KEY_PATH,
    tool_name: str = "CLI",
    login_command: str = "<tool> login",
) -> None:
    while True:
        status = read_credentials_status(path, expiry_key_path=expiry_key_path)
        if status.readable:
            if status.is_expired:
                logger.error(
                    "%s login expired — run `%s` to re-authenticate (credentials file: %s)",
                    tool_name,
                    login_command,
                    status.path,
                )
            elif status.is_near_expiry(warning_threshold_s):
                days_left = (status.seconds_remaining or 0) / _SECONDS_PER_DAY
                logger.warning(
                    "%s login expires in %.1f day(s) — run `%s` soon to avoid an outage (credentials file: %s)",
                    tool_name,
                    days_left,
                    login_command,
                    status.path,
                )
        await asyncio.sleep(interval_s)
