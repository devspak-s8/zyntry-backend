from __future__ import annotations

import base64
import hashlib
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.core.config import settings

_PBKDF2_SALT = b"\x17\x99\xaf\x8c\x72\x3e\x5d\x1b\xa4\xcf\x60\x28\xd4\x93\xb7\x0e"
_PBKDF2_ITERATIONS = 200_000
_KEY_SIZE = 32
_TAG_SIZE = 16
_IV_SIZE = 12
_PREFIX = "ENCV1"


def get_master_key() -> bytes:
    source = settings.ENCRYPTION_KEY or settings.SECRET_KEY
    if not source:
        raise RuntimeError("Encryption key source is not configured")
    return hashlib.pbkdf2_hmac(
        "sha256",
        source.encode("utf-8"),
        _PBKDF2_SALT,
        _PBKDF2_ITERATIONS,
        dklen=_KEY_SIZE,
    )


def _normalize_key(key: bytes | None) -> bytes:
    if key is not None:
        if not isinstance(key, bytes):
            raise TypeError("Key must be bytes")
        if len(key) != _KEY_SIZE:
            raise ValueError("Encryption key must be 32 bytes for AES-256")
        return key
    return get_master_key()


def encrypt_value(plaintext: str, key: bytes | None = None) -> str:
    if not isinstance(plaintext, str):
        raise TypeError("plaintext must be a str")
    key = _normalize_key(key)
    iv = os.urandom(_IV_SIZE)
    aesgcm = AESGCM(key)
    ciphertext_with_tag = aesgcm.encrypt(iv, plaintext.encode("utf-8"), None)
    tag = ciphertext_with_tag[-_TAG_SIZE:]
    ciphertext = ciphertext_with_tag[:-_TAG_SIZE]
    return ":".join(
        [
            _PREFIX,
            base64.b64encode(iv).decode("ascii"),
            base64.b64encode(tag).decode("ascii"),
            base64.b64encode(ciphertext).decode("ascii"),
        ]
    )


def decrypt_value(ciphertext: str, key: bytes | None = None) -> str:
    key = _normalize_key(key)
    if not ciphertext.startswith(_PREFIX + ":"):
        raise ValueError("Invalid ciphertext format")
    parts = ciphertext.split(":", 3)
    if len(parts) != 4:
        raise ValueError("Invalid ciphertext format")
    _, iv_b64, tag_b64, ct_b64 = parts
    try:
        iv = base64.b64decode(iv_b64)
        tag = base64.b64decode(tag_b64)
        ciphertext_bytes = base64.b64decode(ct_b64)
    except Exception:
        raise ValueError("Invalid ciphertext encoding") from None
    if len(iv) != _IV_SIZE:
        raise ValueError("Invalid IV length")
    ciphertext_with_tag = ciphertext_bytes + tag
    aesgcm = AESGCM(key)
    try:
        plaintext = aesgcm.decrypt(iv, ciphertext_with_tag, None)
    except Exception:
        raise ValueError("Failed to decrypt value") from None
    return plaintext.decode("utf-8")


def rotate_key(ciphertext: str, old_key: bytes, new_key: bytes) -> str:
    if len(old_key) != _KEY_SIZE or len(new_key) != _KEY_SIZE:
        raise ValueError("Encryption keys must be 32 bytes for AES-256")
    plaintext = decrypt_value(ciphertext, old_key)
    return encrypt_value(plaintext, new_key)
