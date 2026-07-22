from __future__ import annotations

import asyncio
import hashlib
import hmac
import itertools
import json
import logging
import os
import secrets
import stat
import threading
import time
from collections import deque
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import jwt

logger = logging.getLogger(__name__)

# OWASP 2023 minimum for interactive login (2^17). Existing installs keep whatever N
# they were hashed with — see set_password()/verify_password(), which persist the KDF
# params used at hash time instead of assuming the current module constant, so bumping
# this value never invalidates passwords set under an older version.
_SCRYPT_N = 131072
_SCRYPT_R = 8
_SCRYPT_P = 1
_SCRYPT_DKLEN = 32

# Params used by every hash written before scrypt_n/r/p started being persisted
# (module versions <=0.1.4, N=16384). A hash with no stored params must be verified
# against these, not the current _SCRYPT_N above, or every pre-existing password breaks.
_LEGACY_SCRYPT_N = 16384
_LEGACY_SCRYPT_R = 8
_LEGACY_SCRYPT_P = 1

# hashlib.scrypt's OpenSSL backend defaults maxmem to 32MB, well under what N=131072,
# r=8 needs (128*N*r*p bytes ≈ 128MB) — without raising it, hashing raises ValueError:
# "memory limit exceeded". Sized generously above the largest params this module uses.
_SCRYPT_MAXMEM = 256 * 1024 * 1024

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
        self._save_lock = threading.Lock()
        self._tmp_counter = itertools.count()
        self._data: dict[str, Any] = self._load_or_init()
        self._failed_attempts: dict[str, list[float]] = {}
        self._blocked_until: dict[str, float] = {}
        self._global_attempts: deque[float] = deque()

    def _load_or_init(self) -> dict[str, Any]:
        try:
            raw = self.auth_file.read_text(encoding="utf-8")
        except FileNotFoundError:
            data: dict[str, Any] = {
                "password_hash": None,
                "salt": None,
                "secret": secrets.token_hex(32),
                "ui_storage_secret": secrets.token_hex(16),
            }
            self._save(data)
            logger.warning("no password configured yet; run scripts/set_password.py before logging in")
            return data
        loaded: dict[str, Any] = json.loads(raw)
        if "ui_storage_secret" not in loaded:
            loaded["ui_storage_secret"] = secrets.token_hex(16)
            self._save(loaded)
        return loaded

    def _save(self, data: dict[str, Any]) -> None:
        # Write to a sibling temp file then atomically rename over the target — a crash
        # mid-write can never leave auth.json truncated/unparsable. The secret (used to
        # sign every session JWT) lives in this file, so a corrupted read would silently
        # invalidate all active sessions. The temp file uses a per-call unique suffix
        # (pid + monotonic counter) rather than a static ".tmp" name, so two concurrent
        # _save calls can never clobber each other's temp file before the rename.
        self.auth_file.parent.mkdir(parents=True, exist_ok=True)
        with self._save_lock:
            tmp_path = self.auth_file.with_suffix(f".{os.getpid()}.{next(self._tmp_counter)}.tmp")
            tmp_path.write_text(json.dumps(data), encoding="utf-8")
            os.replace(tmp_path, self.auth_file)
        try:
            os.chmod(self.auth_file, stat.S_IRUSR | stat.S_IWUSR)  # owner read/write only
        except OSError:
            pass  # best-effort — e.g. unsupported on this filesystem/OS (Windows)

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
            password.encode("utf-8"),
            salt=salt,
            n=_SCRYPT_N,
            r=_SCRYPT_R,
            p=_SCRYPT_P,
            dklen=_SCRYPT_DKLEN,
            maxmem=_SCRYPT_MAXMEM,
        )
        self._data["salt"] = salt.hex()
        self._data["password_hash"] = digest.hex()
        # Persist the KDF params used at hash time, not just the hash — lets a future
        # bump of the module-level _SCRYPT_N constant tighten cost for new passwords
        # without invalidating (or silently under-verifying) hashes set under an older N.
        self._data["scrypt_n"] = _SCRYPT_N
        self._data["scrypt_r"] = _SCRYPT_R
        self._data["scrypt_p"] = _SCRYPT_P
        self._save(self._data)

    def verify_password(self, password: str) -> bool:
        """Constant-time check of password against the stored hash."""
        salt_hex = self._data.get("salt")
        hash_hex = self._data.get("password_hash")
        if not salt_hex or not hash_hex:
            return False
        salt = bytes.fromhex(salt_hex)
        n = self._data.get("scrypt_n", _LEGACY_SCRYPT_N)
        r = self._data.get("scrypt_r", _LEGACY_SCRYPT_R)
        p = self._data.get("scrypt_p", _LEGACY_SCRYPT_P)
        digest = hashlib.scrypt(
            password.encode("utf-8"), salt=salt, n=n, r=r, p=p, dklen=_SCRYPT_DKLEN, maxmem=_SCRYPT_MAXMEM
        )
        return hmac.compare_digest(digest, bytes.fromhex(hash_hex))

    def create_token(self) -> str:
        """Issue a JWT session token valid for token_ttl seconds."""
        payload = {"exp": int(time.time()) + self.token_ttl}
        return jwt.encode(payload, self._data["secret"], algorithm="HS256", headers={"typ": "JWT"})

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
    # Compare against every token rather than short-circuiting on the first match —
    # any()'s early exit leaks which position in valid_tokens matched via timing,
    # in principle allowing a binary search of a large token set.
    return sum(hmac.compare_digest(presented, token) for token in valid_tokens) > 0


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
