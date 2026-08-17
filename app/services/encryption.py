from __future__ import annotations

from app.services.security.secrets import default_secret_manager


def get_master_key() -> bytes:
    return default_secret_manager._normalize_key()


def encrypt_value(plaintext: str, key: bytes | None = None) -> str:
    return default_secret_manager.encrypt(plaintext, key)


def decrypt_value(ciphertext: str, key: bytes | None = None) -> str:
    return default_secret_manager.decrypt(ciphertext, key)


def rotate_key(ciphertext: str, old_key: bytes, new_key: bytes) -> str:
    return default_secret_manager.rotate(ciphertext, old_key, new_key)
