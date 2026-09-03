"""Symmetric encryption for secrets at rest (ApiKey.key_value, OAuth tokens).

Uses Fernet (AES-128-CBC + HMAC) with a key from Config.encryption_key, per
PROJECT_OUTLINE.md §2 "Secret encryption".
"""

from functools import lru_cache

from cryptography.fernet import Fernet

from app.config import get_config


@lru_cache
def _fernet() -> Fernet:
    return Fernet(get_config().encryption_key.encode())


def encrypt(plaintext: str) -> str:
    return _fernet().encrypt(plaintext.encode()).decode()


def decrypt(ciphertext: str) -> str:
    return _fernet().decrypt(ciphertext.encode()).decode()
