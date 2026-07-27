from __future__ import annotations

import json
import sys
import os

# Add backend to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "backend"))

# Mock settings before importing encryption
class MockSettings:
    SECRET_KEY = "test-secret-key-for-unit-testing-only"
    ENCRYPTION_KEY = ""

import app.core.config
app.core.config.settings = MockSettings()

from app.services.encryption import encrypt_value, decrypt_value, rotate_key, get_master_key


def main() -> None:
    plaintext = json.dumps({"api_key": "secret123", "token": "abc"})
    key = get_master_key()
    print("Master key length:", len(key))
    assert len(key) == 32

    ct = encrypt_value(plaintext)
    print("Encrypted:", ct)
    assert ct.startswith("ENCV1:")
    parts = ct.split(":")
    assert len(parts) == 4

    pt = decrypt_value(ct)
    print("Decrypted:", pt)
    assert pt == plaintext

    custom_key = bytes(range(32))
    ct2 = encrypt_value(plaintext, custom_key)
    pt2 = decrypt_value(ct2, custom_key)
    assert pt2 == plaintext

    new_key = bytes(range(31, 63))
    ct3 = rotate_key(ct2, custom_key, new_key)
    pt3 = decrypt_value(ct3, new_key)
    assert pt3 == plaintext

    try:
        decrypt_value("invalid")
    except ValueError as e:
        print("Caught expected error:", e)

    try:
        decrypt_value("ENCV1:invalid")
    except ValueError as e:
        print("Caught expected error:", e)

    print("All tests passed")


if __name__ == "__main__":
    main()
