# -*- coding: utf-8 -*-
"""Single-user authentication primitives: password hashing, sessions, limits.

No accounts, roles or tenants. One owner password protects a web instance that
is reachable from a LAN or the internet. Local loopback use can stay passwordless
when the operator explicitly runs in local-only mode.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import time

PBKDF2_ITERATIONS = 240_000
SESSION_TTL_S = 12 * 3600


class AuthError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def hash_password(password: str, iterations: int = PBKDF2_ITERATIONS) -> dict:
    if not password or len(password) < 8:
        raise AuthError("E_WEAK_PASSWORD", "密码至少 8 位")
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return {
        "algo": "pbkdf2_sha256",
        "iterations": int(iterations),
        "salt": salt.hex(),
        "hash": digest.hex(),
    }


def verify_password(password: str, record: dict | None) -> bool:
    if not record or not password:
        return False
    try:
        salt = bytes.fromhex(record["salt"])
        expected = bytes.fromhex(record["hash"])
        iterations = int(record.get("iterations") or PBKDF2_ITERATIONS)
    except (KeyError, ValueError, TypeError):
        return False
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return hmac.compare_digest(digest, expected)


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _unb64(text: str) -> bytes:
    padding = "=" * (-len(text) % 4)
    return base64.urlsafe_b64decode(text + padding)


class SessionManager:
    """HMAC-signed stateless session tokens bound to a session epoch."""

    def __init__(self, secret_hex: str, epoch: int = 1, ttl: int = SESSION_TTL_S):
        self.secret = bytes.fromhex(secret_hex)
        self.epoch = int(epoch)
        self.ttl = int(ttl)

    def issue(self, now: float | None = None) -> str:
        issued = int(now if now is not None else time.time())
        payload = f"{self.epoch}.{issued}.{issued + self.ttl}"
        sig = hmac.new(self.secret, payload.encode("ascii"), hashlib.sha256).hexdigest()
        return _b64(f"{payload}.{sig}".encode("ascii"))

    def verify(self, token: str | None, now: float | None = None) -> bool:
        if not token:
            return False
        try:
            raw = _unb64(token).decode("ascii")
            epoch, issued, expiry, sig = raw.split(".")
            expected = hmac.new(self.secret, f"{epoch}.{issued}.{expiry}".encode("ascii"),
                                hashlib.sha256).hexdigest()
        except (ValueError, UnicodeDecodeError):
            return False
        if not hmac.compare_digest(sig, expected):
            return False
        current = int(now if now is not None else time.time())
        return int(epoch) == self.epoch and int(issued) <= current < int(expiry)


class LoginLimiter:
    """Per-IP failure window; in-memory, resets on restart."""

    def __init__(self, max_attempts: int = 5, window_s: int = 600):
        self.max_attempts = max(1, int(max_attempts))
        self.window_s = max(1, int(window_s))
        self.failures: dict[str, list[float]] = {}

    def _prune(self, ip: str, now: float):
        cutoff = now - self.window_s
        self.failures[ip] = [t for t in self.failures.get(ip, []) if t > cutoff]

    def blocked(self, ip: str, now: float | None = None) -> tuple[bool, int]:
        now = now if now is not None else time.time()
        self._prune(ip, now)
        items = self.failures.get(ip, [])
        if len(items) >= self.max_attempts:
            retry = max(1, int(self.window_s - (now - items[0])))
            return True, retry
        return False, 0

    def fail(self, ip: str, now: float | None = None):
        now = now if now is not None else time.time()
        self._prune(ip, now)
        self.failures.setdefault(ip, []).append(now)

    def success(self, ip: str):
        self.failures.pop(ip, None)


def is_loopback(host: str) -> bool:
    return (host or "").strip().lower() in ("127.0.0.1", "::1", "localhost")
