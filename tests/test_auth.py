from __future__ import annotations

import time
from pathlib import Path

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


def test_client_ip_trusts_only_known_proxies() -> None:
    trusted = {"127.0.0.1"}
    assert client_ip({"cf-connecting-ip": "5.6.7.8"}, "127.0.0.1", trusted) == "5.6.7.8"
    assert client_ip({"cf-connecting-ip": "5.6.7.8"}, "10.0.0.1", trusted) == "10.0.0.1"
