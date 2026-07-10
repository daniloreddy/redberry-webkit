from __future__ import annotations

import time
from pathlib import Path

from redberry_webkit.config import ConfigManager


def test_missing_env_file_falls_back_to_defaults(tmp_path: Path) -> None:
    config = ConfigManager(defaults={"FOO": "default"}, env_path=tmp_path / "missing.env")
    assert config.get("FOO") == "default"


def test_env_file_overrides_defaults(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("FOO=from-env\n", encoding="utf-8")
    config = ConfigManager(defaults={"FOO": "default"}, env_path=env_file)
    assert config.get("FOO") == "from-env"


def test_get_bool_and_get_int(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("FLAG=true\nCOUNT=42\n", encoding="utf-8")
    config = ConfigManager(env_path=env_file)
    assert config.get_bool("FLAG") is True
    assert config.get_int("COUNT") == 42
    assert config.get_int("MISSING", 7) == 7


def test_get_public_masks_secret_keys(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("API_TOKEN=shh\nPUBLIC_VAL=visible\n", encoding="utf-8")
    config = ConfigManager(secret_keys={"API_TOKEN"}, env_path=env_file)
    public = config.get_public()
    assert public["API_TOKEN"] == "***"
    assert public["PUBLIC_VAL"] == "visible"


def test_update_many_writes_back_and_updates_cache(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("FOO=old\n", encoding="utf-8")
    config = ConfigManager(env_path=env_file)
    config.update_many({"FOO": "new"})
    assert config.get("FOO") == "new"
    assert "FOO=new" in env_file.read_text(encoding="utf-8")


def test_reload_if_stale_picks_up_external_edits(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("FOO=old\n", encoding="utf-8")
    config = ConfigManager(env_path=env_file)
    assert config.reload_if_stale() is False

    time.sleep(0.01)
    env_file.write_text("FOO=new\n", encoding="utf-8")
    import os

    future = time.time() + 5
    os.utime(env_file, (future, future))

    assert config.reload_if_stale() is True
    assert config.get("FOO") == "new"
