"""Shared-secret auth: password hashing + signed httpOnly session cookie.

Single-user app (PROJECT_OUTLINE.md §2 "App access") — there's no user
table, just one secret gating the whole app and a signed cookie proving a
browser already presented it.

Secret hashing is PBKDF2-HMAC-SHA256 via the standard library (no
passlib/bcrypt): passlib's bcrypt backend is incompatible with modern
`bcrypt` releases (>=4.1 raises instead of truncating on its own internal
>72-byte self-test), and PBKDF2 needs no extra dependency at all for a
single secret compared this rarely.
"""

import hashlib
import hmac
import os

from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from app.config import get_config

_SESSION_PAYLOAD = "authenticated"

_PBKDF2_ITERATIONS = 600_000
_SALT_BYTES = 16


def hash_secret(secret: str) -> str:
    salt = os.urandom(_SALT_BYTES)
    digest = hashlib.pbkdf2_hmac("sha256", secret.encode(), salt, _PBKDF2_ITERATIONS)
    return f"pbkdf2_sha256${_PBKDF2_ITERATIONS}${salt.hex()}${digest.hex()}"


def verify_secret(secret: str, secret_hash: str) -> bool:
    try:
        scheme, iterations_str, salt_hex, digest_hex = secret_hash.split("$")
        if scheme != "pbkdf2_sha256":
            return False
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(digest_hex)
    except ValueError:
        return False

    actual = hashlib.pbkdf2_hmac("sha256", secret.encode(), salt, int(iterations_str))
    return hmac.compare_digest(actual, expected)


def _serializer() -> URLSafeTimedSerializer:
    config = get_config()
    return URLSafeTimedSerializer(config.session_secret, salt="music-badger-session")


def create_session_token() -> str:
    return _serializer().dumps(_SESSION_PAYLOAD)


def verify_session_token(token: str) -> bool:
    config = get_config()
    try:
        payload = _serializer().loads(token, max_age=config.session_max_age_seconds)
    except (BadSignature, SignatureExpired):
        return False
    return payload == _SESSION_PAYLOAD
