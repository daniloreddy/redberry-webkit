from __future__ import annotations

import json
import time
from pathlib import Path

from redberry_webkit.credentials import read_credentials_status, resolve_credentials_path


def _write_credentials(path: Path, refresh_token_expires_at_ms: int) -> None:
    path.write_text(
        json.dumps({"claudeAiOauth": {"refreshTokenExpiresAt": refresh_token_expires_at_ms}}),
        encoding="utf-8",
    )


def test_resolve_credentials_path_uses_config_dir(tmp_path: Path) -> None:
    resolved = resolve_credentials_path(str(tmp_path))
    assert resolved == tmp_path / ".credentials.json"


def test_resolve_credentials_path_defaults_to_home() -> None:
    resolved = resolve_credentials_path("")
    assert resolved == Path.home() / ".claude" / ".credentials.json"


def test_resolve_credentials_path_custom_dir_and_filename(tmp_path: Path) -> None:
    resolved = resolve_credentials_path(str(tmp_path), filename="tokens.json")
    assert resolved == tmp_path / "tokens.json"


def test_missing_file_is_not_readable_and_not_expired(tmp_path: Path) -> None:
    status = read_credentials_status(tmp_path / ".credentials.json")
    assert status.readable is False
    assert status.is_expired is False
    assert status.is_near_expiry(999999) is False


def test_malformed_file_is_not_readable(tmp_path: Path) -> None:
    path = tmp_path / ".credentials.json"
    path.write_text("not json", encoding="utf-8")
    status = read_credentials_status(path)
    assert status.readable is False


def test_missing_field_is_not_readable(tmp_path: Path) -> None:
    path = tmp_path / ".credentials.json"
    path.write_text(json.dumps({"claudeAiOauth": {}}), encoding="utf-8")
    status = read_credentials_status(path)
    assert status.readable is False


def test_future_expiry_beyond_threshold_is_not_expired_or_near(tmp_path: Path) -> None:
    path = tmp_path / ".credentials.json"
    _write_credentials(path, int((time.time() + 30 * 86400) * 1000))
    status = read_credentials_status(path)
    assert status.readable is True
    assert status.is_expired is False
    assert status.is_near_expiry(7 * 86400) is False


def test_expiry_within_threshold_is_near_expiry(tmp_path: Path) -> None:
    path = tmp_path / ".credentials.json"
    _write_credentials(path, int((time.time() + 2 * 86400) * 1000))
    status = read_credentials_status(path)
    assert status.readable is True
    assert status.is_expired is False
    assert status.is_near_expiry(7 * 86400) is True


def test_past_expiry_is_expired(tmp_path: Path) -> None:
    path = tmp_path / ".credentials.json"
    _write_credentials(path, int((time.time() - 3600) * 1000))
    status = read_credentials_status(path)
    assert status.readable is True
    assert status.is_expired is True
    assert status.is_near_expiry(7 * 86400) is False


def test_custom_expiry_key_path(tmp_path: Path) -> None:
    path = tmp_path / "tokens.json"
    path.write_text(
        json.dumps({"oauth": {"expiresAt": int((time.time() + 2 * 86400) * 1000)}}),
        encoding="utf-8",
    )
    status = read_credentials_status(path, expiry_key_path=("oauth", "expiresAt"))
    assert status.readable is True
    assert status.is_near_expiry(7 * 86400) is True
