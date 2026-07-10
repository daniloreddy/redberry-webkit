from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import os
import secrets
import time
from collections import deque
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import jwt

logger = logging.getLogger(__name__)

_SCRYPT_N = 16384
_SCRYPT_R = 8
_SCRYPT_P = 1
_SCRYPT_DKLEN = 32

_FAILED_ATTEMPTS_LIMIT = 5
_FAILED_ATTEMPTS_WINDOW_S = 300
_IP_BLOCK_DURATION_S = 300
_GLOBAL_ATTEMPTS_LIMIT = 20
_GLOBAL_ATTEMPTS_WINDOW_S = 60


class AuthManager:
    """Cookie/JWT dashboard auth: scrypt password hashing, JWT sessions, per-IP + global rate limiting."""

    def __init__(self, *, auth_file: Path, cookie_name: str, token_ttl: int) -> None:
        self.auth_file = auth_file
        self.cookie_name = cookie_name
        self.token_ttl = token_ttl
        self._data: dict[str, Any] = self._load_or_init()
        self._failed_attempts: dict[str, list[float]] = {}
        self._blocked_until: dict[str, float] = {}
        self._global_attempts: deque[float] = deque()

    def _load_or_init(self) -> dict[str, Any]:
        if self.auth_file.exists():
            loaded: dict[str, Any] = json.loads(self.auth_file.read_text(encoding="utf-8"))
            if "ui_storage_secret" not in loaded:
                loaded["ui_storage_secret"] = secrets.token_hex(16)
                self._save(loaded)
            return loaded
        data: dict[str, Any] = {
            "password_hash": None,
            "salt": None,
            "secret": secrets.token_hex(32),
            "ui_storage_secret": secrets.token_hex(16),
        }
        self._save(data)
        logger.warning("no password configured yet; run scripts/set_password.py before logging in")
        return data

    def _save(self, data: dict[str, Any]) -> None:
        self.auth_file.parent.mkdir(parents=True, exist_ok=True)
        self.auth_file.write_text(json.dumps(data), encoding="utf-8")

    @property
    def ui_storage_secret(self) -> str:
        """Per-install secret for NiceGUI's app.storage.user encryption."""
        secret: str = self._data["ui_storage_secret"]
        return secret

    def has_password(self) -> bool:
        """True if a password has been configured via set_password()."""
        return bool(self._data.get("password_hash"))

    def set_password(self, password: str) -> None:
        """Hash and persist password, overwriting any previous credential."""
        salt = secrets.token_bytes(16)
        digest = hashlib.scrypt(
            password.encode("utf-8"), salt=salt, n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P, dklen=_SCRYPT_DKLEN
        )
        self._data["salt"] = salt.hex()
        self._data["password_hash"] = digest.hex()
        self._save(self._data)

    def verify_password(self, password: str) -> bool:
        """Constant-time check of password against the stored hash."""
        salt_hex = self._data.get("salt")
        hash_hex = self._data.get("password_hash")
        if not salt_hex or not hash_hex:
            return False
        salt = bytes.fromhex(salt_hex)
        digest = hashlib.scrypt(
            password.encode("utf-8"), salt=salt, n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P, dklen=_SCRYPT_DKLEN
        )
        return hmac.compare_digest(digest, bytes.fromhex(hash_hex))

    def create_token(self) -> str:
        """Issue a JWT session token valid for token_ttl seconds."""
        payload = {"exp": int(time.time()) + self.token_ttl}
        return jwt.encode(payload, self._data["secret"], algorithm="HS256")

    def verify_token(self, token: str) -> bool:
        """True if token is a valid, unexpired session JWT."""
        if not token:
            return False
        try:
            jwt.decode(token, self._data["secret"], algorithms=["HS256"])
        except jwt.PyJWTError:
            return False
        return True

    def is_ip_blocked(self, ip: str) -> bool:
        """True if ip is currently locked out from repeated failed login attempts."""
        blocked_until = self._blocked_until.get(ip)
        return blocked_until is not None and blocked_until > time.time()

    def is_global_limited(self) -> bool:
        """True if the global login-attempt rate limit has been hit in the current window."""
        now = time.time()
        while self._global_attempts and self._global_attempts[0] < now - _GLOBAL_ATTEMPTS_WINDOW_S:
            self._global_attempts.popleft()
        return len(self._global_attempts) >= _GLOBAL_ATTEMPTS_LIMIT

    def record_attempt(self, ip: str, *, success: bool) -> None:
        """Record a login attempt for ip; blocks the ip after _FAILED_ATTEMPTS_LIMIT failures."""
        now = time.time()
        self._global_attempts.append(now)
        if success:
            self._failed_attempts.pop(ip, None)
            self._blocked_until.pop(ip, None)
            return
        attempts = self._failed_attempts.setdefault(ip, [])
        attempts.append(now)
        attempts[:] = [t for t in attempts if t > now - _FAILED_ATTEMPTS_WINDOW_S]
        if len(attempts) >= _FAILED_ATTEMPTS_LIMIT:
            self._blocked_until[ip] = now + _IP_BLOCK_DURATION_S

    def purge_expired_blocks(self) -> None:
        """Drop IP blocks and failed-attempt history past expiry — call periodically."""
        now = time.time()
        expired = [ip for ip, until in self._blocked_until.items() if until <= now]
        for ip in expired:
            del self._blocked_until[ip]
            self._failed_attempts.pop(ip, None)


def verify_api_token(authorization_header: str, valid_tokens: set[str]) -> bool:
    """True if the Authorization header carries a valid Bearer token from valid_tokens."""
    if not authorization_header.startswith("Bearer "):
        return False
    presented = authorization_header.removeprefix("Bearer ").strip()
    return any(hmac.compare_digest(presented, token) for token in valid_tokens)


def is_secure_context(headers: Mapping[str, str]) -> bool:
    """True if the request arrived over HTTPS, directly or via a TLS-terminating proxy."""
    if os.getenv("AUTH_SECURE_COOKIE") == "1":
        return True
    return headers.get("x-forwarded-proto") == "https"


def client_ip(headers: Mapping[str, str], client_host: str, trusted_proxies: set[str]) -> str:
    """Resolve the real client IP, trusting forwarded headers only from trusted_proxies."""
    if client_host in trusted_proxies:
        cf = headers.get("cf-connecting-ip", "")
        if cf:
            return cf
        fwd = headers.get("x-forwarded-for", "")
        if fwd:
            return fwd.split(",")[0].strip()
    return client_host or "unknown"


async def purge_loop(auth: AuthManager, interval_s: int = 600) -> None:
    """Background loop: purge expired IP blocks from auth every interval_s seconds."""
    while True:
        await asyncio.sleep(interval_s)
        auth.purge_expired_blocks()
