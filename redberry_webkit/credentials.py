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
    """Snapshot of a CLI tool's OAuth credential expiry, read from its JSON credentials file."""

    path: Path
    readable: bool
    expires_at_ms: int | None
    checked_at: float

    @property
    def seconds_remaining(self) -> float | None:
        """Seconds until expiry as of checked_at, or None if expiry is unknown."""
        if self.expires_at_ms is None:
            return None
        return self.expires_at_ms / 1000 - self.checked_at

    @property
    def is_expired(self) -> bool:
        """True if the credential had already expired as of checked_at."""
        remaining = self.seconds_remaining
        return remaining is not None and remaining <= 0

    def is_near_expiry(self, warning_threshold_s: float) -> bool:
        """True if the credential expires within warning_threshold_s seconds."""
        remaining = self.seconds_remaining
        return remaining is not None and 0 < remaining <= warning_threshold_s


def resolve_credentials_path(
    config_dir: str = "", *, default_dir_name: str = ".claude", filename: str = ".credentials.json"
) -> Path:
    """Resolve the on-disk path to a CLI tool's credentials file (default: ~/.claude/.credentials.json).

    `config_dir` must come from trusted config (env var, CLI flag), never directly from
    untrusted request input — it is not sandboxed to any base directory, so an attacker-
    controlled value (e.g. `../../etc`) resolves outside the intended config directory.
    """
    base = Path(config_dir).resolve() if config_dir.strip() else Path.home() / default_dir_name
    return base / filename


def read_credentials_status(
    path: Path, *, expiry_key_path: Sequence[str] = _DEFAULT_EXPIRY_KEY_PATH
) -> CredentialsStatus:
    """Read and parse expiry info from the credentials file at path."""
    now = time.time()
    try:
        # Read directly instead of checking .exists() first — an exists()-then-read_text()
        # pair is a TOCTOU window where the file can vanish or be swapped in between.
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return CredentialsStatus(path=path, readable=False, expires_at_ms=None, checked_at=now)
    except OSError as exc:
        logger.warning("credentials file at %s unreadable: %s", path, type(exc).__name__)
        return CredentialsStatus(path=path, readable=False, expires_at_ms=None, checked_at=now)
    try:
        value: Any = json.loads(raw)
        for key in expiry_key_path:
            value = value[key]
        return CredentialsStatus(path=path, readable=True, expires_at_ms=int(value), checked_at=now)
    except (ValueError, KeyError, TypeError) as exc:
        # Log the exception type only, not its message — a JSON/KeyError message can
        # echo back fragments of the file content, which may itself be sensitive.
        logger.warning("credentials file at %s malformed: %s", path, type(exc).__name__)
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
    """Background loop: log a warning/error as tool_name's credentials approach or pass expiry."""
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
