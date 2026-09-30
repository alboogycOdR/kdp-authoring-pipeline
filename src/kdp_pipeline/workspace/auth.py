from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import time


_USERNAME = re.compile(r"^[A-Za-z0-9._@+-]{1,80}$")
_HASH_VERSION = "scrypt-v1"
_HASH_N = 2**14
_HASH_R = 8
_HASH_P = 5
_HASH_BYTES = 32
_HASH_MAXMEM = 64 * 1024 * 1024
SESSION_SECONDS = 12 * 60 * 60
REMEMBER_SECONDS = 30 * 24 * 60 * 60


class WorkspaceAuth:
    """Single-operator password authentication and signed browser sessions."""

    def __init__(self, username: str | None, password_hash: str | None,
                 signing_key: bytes | None, *, configured: bool):
        self.username = username or ""
        self.password_hash = password_hash or ""
        self.signing_key = signing_key or b""
        self.configured = configured

    @classmethod
    def from_environment(cls) -> "WorkspaceAuth":
        username = os.environ.get("KDP_WORKSPACE_USERNAME", "").strip()
        password_hash = os.environ.get("KDP_WORKSPACE_PASSWORD_HASH", "").strip()
        if not username and not password_hash:
            return cls(None, None, None, configured=False)
        if not _USERNAME.fullmatch(username):
            raise ValueError("KDP_WORKSPACE_USERNAME must be 1–80 letters, numbers, or . _ @ + -")
        _parse_hash(password_hash)
        master_key = os.environ.get("KDP_WORKSPACE_SESSION_SECRET", "").encode("utf-8")
        if len(master_key) < 32:
            raise ValueError("KDP_WORKSPACE_SESSION_SECRET must contain at least 32 characters")
        session_key = hmac.new(master_key, password_hash.encode("ascii"), hashlib.sha256).digest()
        return cls(username, password_hash, session_key, configured=True)

    def verify(self, username: str, password: str) -> bool:
        submitted_user = username.strip()
        user_ok = hmac.compare_digest(submitted_user.casefold(), self.username.casefold())
        if len(submitted_user) > 80 or len(password.encode("utf-8")) > 1024:
            return False
        try:
            password_ok = verify_password(password, self.password_hash)
        except (ValueError, MemoryError):
            password_ok = False
        return self.configured and user_ok and password_ok

    def issue(self, *, remember: bool, now: int | None = None) -> tuple[str, int]:
        issued = int(time.time()) if now is None else int(now)
        duration = REMEMBER_SECONDS if remember else SESSION_SECONDS
        payload = json.dumps({"u": self.username, "e": issued + duration,
                              "n": secrets.token_urlsafe(24)}, separators=(",", ":")).encode()
        body = _b64(payload)
        signature = _b64(hmac.new(self.signing_key, body.encode("ascii"), hashlib.sha256).digest())
        return f"{body}.{signature}", duration

    def validate(self, token: str, *, now: int | None = None) -> str | None:
        if not self.configured or len(token) > 2048:
            return None
        try:
            body, supplied_signature = token.split(".", 1)
            expected = _b64(hmac.new(self.signing_key, body.encode("ascii"), hashlib.sha256).digest())
            if not hmac.compare_digest(supplied_signature, expected):
                return None
            payload = json.loads(_unb64(body))
            if not isinstance(payload, dict) or not isinstance(payload.get("u"), str):
                return None
            current = int(time.time()) if now is None else int(now)
            if (payload.get("u", "").casefold() != self.username.casefold()
                    or not isinstance(payload.get("e"), int) or payload["e"] <= current
                    or not isinstance(payload.get("n"), str) or len(payload["n"]) < 24):
                return None
            return self.username
        except (ValueError, TypeError, UnicodeError):
            return None


def hash_password(password: str) -> str:
    if len(password) < 14:
        raise ValueError("Use a password with at least 14 characters.")
    if len(password.encode("utf-8")) > 1024:
        raise ValueError("Use a password no longer than 1024 UTF-8 bytes.")
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=_HASH_N,
                            r=_HASH_R, p=_HASH_P, dklen=_HASH_BYTES,
                            maxmem=_HASH_MAXMEM)
    return "$".join((_HASH_VERSION, str(_HASH_N), str(_HASH_R), str(_HASH_P),
                     _b64(salt), _b64(digest)))


def verify_password(password: str, encoded: str) -> bool:
    n, r, p, salt, expected = _parse_hash(encoded)
    candidate = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=n,
                               r=r, p=p, dklen=len(expected), maxmem=_HASH_MAXMEM)
    return hmac.compare_digest(candidate, expected)


def _parse_hash(encoded: str) -> tuple[int, int, int, bytes, bytes]:
    parts = encoded.split("$")
    if len(parts) != 6 or parts[0] != _HASH_VERSION:
        raise ValueError("KDP_WORKSPACE_PASSWORD_HASH is invalid; generate it with the workspace CLI.")
    try:
        n, r, p = (int(value) for value in parts[1:4])
        salt, expected = _unb64(parts[4]), _unb64(parts[5])
    except (ValueError, TypeError) as exc:
        raise ValueError("KDP_WORKSPACE_PASSWORD_HASH is invalid; generate it with the workspace CLI.") from exc
    if (n != _HASH_N or r != _HASH_R or p != _HASH_P
            or len(salt) != 16 or len(expected) != _HASH_BYTES):
        raise ValueError("KDP_WORKSPACE_PASSWORD_HASH uses unsupported parameters.")
    return n, r, p, salt, expected


def _b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _unb64(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
