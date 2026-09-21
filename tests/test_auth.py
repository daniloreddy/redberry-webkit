from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import pytest

from redberry_webkit.auth import AuthManager, client_ip, is_secure_context, verify_api_token


@pytest.fixture
def auth(tmp_path: Path) -> AuthManager:
    return AuthManager(auth_file=tmp_path / "auth.json", cookie_name="test_session", token_ttl=3600)


def test_no_password_by_default(auth: AuthManager) -> None:
    assert auth.has_password() is False
    assert auth.verify_password("anything") is False


def test_set_and_verify_password(auth: AuthManager) -> None:
    auth.set_password("s3cr3t")
    assert auth.has_password() is True
    assert auth.verify_password("s3cr3t") is True
    assert auth.verify_password("wrong") is False


def test_set_password_rotates_jwt_secret_and_invalidates_existing_sessions(auth: AuthManager) -> None:
    auth.set_password("first-password")
    token = auth.create_token()
    assert auth.verify_token(token) is True

    # Changing the password (e.g. after a suspected stolen session cookie) must
    # invalidate every token issued under the old secret, not just future logins.
    auth.set_password("second-password")
    assert auth.verify_token(token) is False
    assert auth.verify_token(auth.create_token()) is True


def test_password_persisted_across_instances(tmp_path: Path) -> None:
    auth_file = tmp_path / "auth.json"
    first = AuthManager(auth_file=auth_file, cookie_name="s", token_ttl=3600)
    first.set_password("s3cr3t")
    second = AuthManager(auth_file=auth_file, cookie_name="s", token_ttl=3600)
    assert second.verify_password("s3cr3t") is True


def test_create_and_verify_token(auth: AuthManager) -> None:
    token = auth.create_token()
    assert auth.verify_token(token) is True
    assert auth.verify_token("garbage") is False
    assert auth.verify_token("") is False


def test_expired_token_is_invalid(tmp_path: Path) -> None:
    short_lived = AuthManager(auth_file=tmp_path / "auth.json", cookie_name="s", token_ttl=-1)
    token = short_lived.create_token()
    assert short_lived.verify_token(token) is False


def test_rate_limit_blocks_after_threshold(auth: AuthManager) -> None:
    ip = "1.2.3.4"
    for _ in range(5):
        auth.record_attempt(ip, success=False)
    assert auth.is_ip_blocked(ip) is True


def test_successful_attempt_clears_block_state(auth: AuthManager) -> None:
    ip = "1.2.3.4"
    for _ in range(4):
        auth.record_attempt(ip, success=False)
    auth.record_attempt(ip, success=True)
    assert auth.is_ip_blocked(ip) is False


def test_global_rate_limit(auth: AuthManager) -> None:
    for _ in range(20):
        auth.record_attempt("distinct-ip", success=False)
    assert auth.is_global_limited() is True


def test_purge_expired_blocks_removes_stale_entries(auth: AuthManager) -> None:
    ip = "9.9.9.9"
    for _ in range(5):
        auth.record_attempt(ip, success=False)
    assert auth.is_ip_blocked(ip) is True
    auth._blocked_until[ip] = time.time() - 1  # force expiry without waiting 5 minutes
    auth.purge_expired_blocks()
    assert auth.is_ip_blocked(ip) is False


def test_verify_api_token() -> None:
    tokens = {"abc123"}
    assert verify_api_token("Bearer abc123", tokens) is True
    assert verify_api_token("Bearer wrong", tokens) is False
    assert verify_api_token("abc123", tokens) is False


def test_is_secure_context_from_header() -> None:
    assert is_secure_context({"x-forwarded-proto": "https"}) is True
    assert is_secure_context({}) is False


def test_is_secure_context_from_env_var(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AUTH_SECURE_COOKIE", "1")
    assert is_secure_context({}) is True


def test_client_ip_trusts_only_known_proxies() -> None:
    trusted = {"127.0.0.1"}
    assert client_ip({"cf-connecting-ip": "5.6.7.8"}, "127.0.0.1", trusted) == "5.6.7.8"
    assert client_ip({"cf-connecting-ip": "5.6.7.8"}, "10.0.0.1", trusted) == "10.0.0.1"


def test_client_ip_falls_back_to_x_forwarded_for(monkeypatch: pytest.MonkeyPatch) -> None:
    trusted = {"127.0.0.1"}
    assert client_ip({"x-forwarded-for": "5.6.7.8, 9.9.9.9"}, "127.0.0.1", trusted) == "5.6.7.8"


def test_client_ip_unknown_when_no_client_host() -> None:
    assert client_ip({}, "", set()) == "unknown"


def test_verify_api_token_multiple_valid_tokens() -> None:
    tokens = {"abc123", "def456"}
    assert verify_api_token("Bearer def456", tokens) is True


def test_verify_api_token_empty_header() -> None:
    assert verify_api_token("", {"abc123"}) is False


def test_verify_api_token_non_ascii_presented_token_rejects_without_raising() -> None:
    # hmac.compare_digest raises TypeError on non-ASCII str operands — must be treated
    # as a no-match (False), never let a malformed/malicious header 500 the caller.
    assert verify_api_token("Bearer café", {"abc123"}) is False


def test_ip_never_attempted_is_not_blocked(auth: AuthManager) -> None:
    assert auth.is_ip_blocked("never-seen") is False


def test_failed_attempts_outside_window_do_not_count_towards_block(auth: AuthManager) -> None:
    ip = "1.2.3.4"
    for _ in range(4):
        auth.record_attempt(ip, success=False)
    stale_cutoff = time.time() - 301
    auth._failed_attempts[ip] = [stale_cutoff] * 4
    auth.record_attempt(ip, success=False)
    assert auth.is_ip_blocked(ip) is False


def test_global_rate_limit_resets_outside_window(auth: AuthManager) -> None:
    stale_cutoff = time.time() - 61
    auth._global_attempts.extend([stale_cutoff] * 20)
    assert auth.is_global_limited() is False


def test_purge_expired_blocks_leaves_active_blocks_untouched(auth: AuthManager) -> None:
    ip = "9.9.9.9"
    for _ in range(5):
        auth.record_attempt(ip, success=False)
    auth.purge_expired_blocks()
    assert auth.is_ip_blocked(ip) is True


def test_purge_expired_blocks_drops_stale_sub_threshold_attempts(auth: AuthManager) -> None:
    # An IP with fewer than _FAILED_ATTEMPTS_LIMIT failures never enters _blocked_until,
    # so it was previously never purged from _failed_attempts — unbounded growth, one
    # entry per distinct IP that ever failed a login once, however long ago.
    ip = "1.2.3.4"
    auth.record_attempt(ip, success=False)
    auth.record_attempt(ip, success=False)
    assert ip in auth._failed_attempts

    auth._failed_attempts[ip] = [time.time() - 301] * 2  # force outside the attempt window
    auth.purge_expired_blocks()
    assert ip not in auth._failed_attempts


def test_purge_expired_blocks_keeps_fresh_sub_threshold_attempts(auth: AuthManager) -> None:
    ip = "1.2.3.4"
    auth.record_attempt(ip, success=False)
    auth.purge_expired_blocks()
    assert ip in auth._failed_attempts


def test_legacy_hash_without_stored_kdf_params_still_verifies(tmp_path: Path) -> None:
    # Simulates a password set before scrypt_n/r/p were persisted (module <=0.1.4,
    # hashed at N=16384). Must still verify under the module's current, higher _SCRYPT_N.
    import hashlib

    from redberry_webkit.auth import _LEGACY_SCRYPT_N, _LEGACY_SCRYPT_P, _LEGACY_SCRYPT_R

    auth_file = tmp_path / "auth.json"
    salt = b"0" * 16
    digest = hashlib.scrypt(
        b"old-password", salt=salt, n=_LEGACY_SCRYPT_N, r=_LEGACY_SCRYPT_R, p=_LEGACY_SCRYPT_P, dklen=32
    )
    auth_file.write_text(
        json.dumps({"password_hash": digest.hex(), "salt": salt.hex(), "secret": "s"}), encoding="utf-8"
    )
    auth = AuthManager(auth_file=auth_file, cookie_name="s", token_ttl=3600)
    assert auth.verify_password("old-password") is True
    assert auth.verify_password("wrong") is False


def test_save_chmods_temp_file_before_rename(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Verifies call ORDER (chmod before replace), not actual POSIX permission bits — dev
    # runs happen on Windows, where chmod is a no-op either way. os.replace() preserves the
    # source file's mode on POSIX, so chmod-ing the temp file before the rename means
    # auth_file (holding the JWT secret) never passes through an umask-determined mode.
    import os as os_module

    calls: list[str] = []
    real_chmod = os_module.chmod
    real_replace = os_module.replace

    def _tracking_chmod(path: Any, mode: int) -> None:
        calls.append(f"chmod:{Path(str(path)).name}")
        real_chmod(path, mode)

    def _tracking_replace(src: Any, dst: Any) -> None:
        calls.append(f"replace:{Path(str(src)).name}")
        real_replace(src, dst)

    monkeypatch.setattr(os_module, "chmod", _tracking_chmod)
    monkeypatch.setattr(os_module, "replace", _tracking_replace)

    auth = AuthManager(auth_file=tmp_path / "auth.json", cookie_name="s", token_ttl=3600)
    calls.clear()
    auth.set_password("x")

    chmod_calls = [c for c in calls if c.startswith("chmod:")]
    replace_calls = [c for c in calls if c.startswith("replace:")]
    assert len(chmod_calls) == 1
    assert len(replace_calls) == 1
    assert calls.index(chmod_calls[0]) < calls.index(replace_calls[0])
    assert "auth.json" not in chmod_calls[0]  # must target the temp file, not the final path


def test_load_existing_file_missing_ui_storage_secret_gets_migrated(tmp_path: Path) -> None:
    auth_file = tmp_path / "auth.json"
    auth_file.write_text(json.dumps({"password_hash": None, "salt": None, "secret": "s"}), encoding="utf-8")
    auth = AuthManager(auth_file=auth_file, cookie_name="s", token_ttl=3600)
    assert auth.ui_storage_secret
    persisted = json.loads(auth_file.read_text(encoding="utf-8"))
    assert persisted["ui_storage_secret"] == auth.ui_storage_secret


async def test_purge_loop_purges_expired_blocks_once(auth: AuthManager) -> None:
    import asyncio

    from redberry_webkit.auth import purge_loop

    ip = "9.9.9.9"
    for _ in range(5):
        auth.record_attempt(ip, success=False)
    auth._blocked_until[ip] = time.time() - 1

    task = asyncio.create_task(purge_loop(auth, interval_s=0))
    await asyncio.sleep(0.05)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert auth.is_ip_blocked(ip) is False
