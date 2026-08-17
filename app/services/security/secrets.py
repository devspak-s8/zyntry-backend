from __future__ import annotations

import base64
import hashlib
import os
import re
from typing import Any, Protocol

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.core.config import settings

_PBKDF2_SALT = b"\x17\x99\xaf\x8c\x72\x3e\x5d\x1b\xa4\xcf\x60\x28\xd4\x93\xb7\x0e"
_PBKDF2_ITERATIONS = 200_000
_KEY_SIZE = 32
_TAG_SIZE = 16
_IV_SIZE = 12
_PREFIX = "ENCV1"

_SENSITIVE_KEYS_RE = re.compile(
    r"(?i)(password|secret|token|api[_-]?key|access[_-]?token|refresh[_-]?token|credential|authorization|auth_code|private_key)"
)


class KeyProvider(Protocol):
    def get_master_key(self) -> bytes:
        ...


class DefaultKeyProvider:
    def get_master_key(self) -> bytes:
        source = settings.ENCRYPTION_KEY or settings.SECRET_KEY or "zyntry_default_secure_dev_key_32b"
        return hashlib.pbkdf2_hmac(
            "sha256",
            source.encode("utf-8"),
            _PBKDF2_SALT,
            _PBKDF2_ITERATIONS,
            dklen=_KEY_SIZE,
        )


class SecretManager:
    def __init__(self, key_provider: KeyProvider | None = None) -> None:
        self.key_provider = key_provider or DefaultKeyProvider()

    def _normalize_key(self, key: bytes | None = None) -> bytes:
        if key is not None:
            if not isinstance(key, bytes):
                raise TypeError("Key must be bytes")
            if len(key) != _KEY_SIZE:
                raise ValueError("Encryption key must be 32 bytes for AES-256")
            return key
        return self.key_provider.get_master_key()

    def encrypt(self, plaintext: str, key: bytes | None = None) -> str:
        if not isinstance(plaintext, str):
            raise TypeError("plaintext must be a str")
        normalized_key = self._normalize_key(key)
        iv = os.urandom(_IV_SIZE)
        aesgcm = AESGCM(normalized_key)
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

    def decrypt(self, ciphertext: str, key: bytes | None = None) -> str:
        normalized_key = self._normalize_key(key)
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
        except Exception as exc:
            raise ValueError("Invalid ciphertext encoding") from exc
        if len(iv) != _IV_SIZE:
            raise ValueError("Invalid IV length")
        ciphertext_with_tag = ciphertext_bytes + tag
        aesgcm = AESGCM(normalized_key)
        try:
            plaintext = aesgcm.decrypt(iv, ciphertext_with_tag, None)
        except Exception as exc:
            raise ValueError("Failed to decrypt value") from exc
        return plaintext.decode("utf-8")

    def rotate(self, ciphertext: str, old_key: bytes, new_key: bytes) -> str:
        if len(old_key) != _KEY_SIZE or len(new_key) != _KEY_SIZE:
            raise ValueError("Encryption keys must be 32 bytes for AES-256")
        plaintext = self.decrypt(ciphertext, old_key)
        return self.encrypt(plaintext, new_key)

    def redact(self, data: Any) -> Any:
        if isinstance(data, dict):
            redacted = {}
            for k, v in data.items():
                if _SENSITIVE_KEYS_RE.search(str(k)):
                    redacted[k] = "[REDACTED]"
                else:
                    redacted[k] = self.redact(v)
            return redacted
        if isinstance(data, list):
            return [self.redact(item) for item in data]
        if isinstance(data, str) and (data.startswith("sk_") or data.startswith("ghp_") or data.startswith("xoxb-")):
            return data[:7] + "..." + "[REDACTED]"
        return data


default_secret_manager = SecretManager()
