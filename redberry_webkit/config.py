from __future__ import annotations

import logging
from pathlib import Path

from dotenv import dotenv_values, set_key

from .env_resolver import resolve_env_path

logger = logging.getLogger(__name__)


class ConfigManager:
    """.env-backed runtime config: hot-reload via mtime polling, write-back via set_key().

    Not a class-level singleton (no __new__/_instance guard): instantiate once per
    project, typically as a module-level `config = ConfigManager(defaults=..., ...)`
    in the app's own config.py, and import that instance everywhere. Python's module
    cache already guarantees single instantiation; a __new__-based singleton would
    silently ignore `defaults`/`secret_keys` passed on any call after the first.
    """

    def __init__(
        self,
        *,
        defaults: dict[str, str] | None = None,
        secret_keys: set[str] | None = None,
        env_path: Path | None = None,
    ) -> None:
        self._defaults: dict[str, str] = dict(defaults or {})
        self._secret_keys: set[str] = set(secret_keys or set())
        self._env_path: Path = env_path or resolve_env_path()
        self._last_mtime: float = 0.0
        self._cache: dict[str, str] = {}
        logger.info("Config: using .env=%s", self._env_path)
        self._load()

    def _load(self) -> None:
        if not self._env_path.exists():
            logger.warning(
                "No .env at %s — falling back to hardcoded defaults only "
                "(check the bind-mount/ENV_FILE if this is Docker).",
                self._env_path,
            )
        merged = dict(self._defaults)
        merged.update({k: v for k, v in dotenv_values(str(self._env_path)).items() if v is not None})
        self._cache = merged
        self._last_mtime = self._env_path.stat().st_mtime if self._env_path.exists() else 0.0

    def reload_if_stale(self) -> bool:
        """Call periodically (e.g. every ~5s from the FastAPI lifespan)."""
        mtime = self._env_path.stat().st_mtime if self._env_path.exists() else 0.0
        if mtime == self._last_mtime:
            return False
        self._load()
        return True

    def get(self, key: str, default: str = "") -> str:
        """Return key's value, or default if unset."""
        return self._cache.get(key, default)

    def get_bool(self, key: str) -> bool:
        """Parse key as a boolean ("true"/"1"/"yes", case-insensitive; anything else is False)."""
        return self._cache.get(key, "false").strip().lower() in ("true", "1", "yes")

    def get_int(self, key: str, default: int = 0) -> int:
        """Parse key as an int, or default if unset/unparsable."""
        try:
            return int(self._cache.get(key, str(default)))
        except ValueError:
            return default

    def get_float(self, key: str, default: float = 0.0) -> float:
        """Parse key as a float, or default if unset/unparsable."""
        try:
            return float(self._cache.get(key, str(default)))
        except ValueError:
            return default

    def get_public(self) -> dict[str, str]:
        """Full config with secret values masked — safe to render in a web-UI config page."""
        return {k: ("***" if k in self._secret_keys and v else v) for k, v in self._cache.items()}

    def update_many(self, updates: dict[str, str]) -> None:
        """Called by the web-UI save handler — writes straight to .env."""
        for key, value in updates.items():
            stripped = value.strip()
            if not stripped:
                continue
            set_key(str(self._env_path), key, stripped, quote_mode="never")
            self._cache[key] = stripped
