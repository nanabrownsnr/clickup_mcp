from __future__ import annotations

import base64
import os

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC


def _decode_key(encryption_key: str) -> bytes:
    """Decode the ENCRYPTION_KEY from URL-safe base64 to raw bytes.

    The encryption key is supplied as URL-safe base64 encoding of a 16, 24,
    or 32-byte AES key.  Decode it first, then validate the decoded length.
    Handles missing padding by adding '=' characters as needed.
    """
    padded = encryption_key
    padding = 4 - len(padded) % 4
    if padding != 4:
        padded += "=" * padding
    decoded = base64.urlsafe_b64decode(padded)
    if len(decoded) not in (16, 24, 32):
        raise ValueError(
            f"Decrypted encryption key must be 16, 24, or 32 bytes "
            f"(got {len(decoded)})"
        )
    return decoded


def derive_key(encryption_key: str, salt: bytes) -> bytes:
    """Derive a Fernet-compatible key from the decrypted encryption key and salt.

    Uses PBKDF2 with the decoded encryption key as the password and persona
    salt.  Produces a 32-byte key suitable for Fernet.

    Parameters are kept compatible with the existing template so that
    existing code calling derive_key(encryption_key, salt) still works.
    """
    raw_key = _decode_key(encryption_key)
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=480000,
    )
    derived = kdf.derive(raw_key)
    # Fernet requires url-safe base64-encoded 32-byte key
    return base64.urlsafe_b64encode(derived)


def encrypt_token(plain_token: str, encryption_key: str, persona_id: str) -> dict:
    """Encrypt a token using the decrypted encryption key and persona-specific salt."""
    salt = persona_id.encode("utf-8")[:16].ljust(16, b"\x00")
    key = derive_key(encryption_key, salt)
    fernet = Fernet(key)
    encrypted = fernet.encrypt(plain_token.encode("utf-8"))
    return {
        "encrypted_token": encrypted.decode("utf-8"),
        "salt": salt.decode("utf-8"),
    }


def decrypt_token(encrypted_data: dict, encryption_key: str, persona_id: str) -> str:
    """Decrypt a token using the decrypted encryption key and persona-specific salt."""
    salt = encrypted_data.get("salt", persona_id.encode("utf-8")[:16].ljust(16, b"\x00"))
    if isinstance(salt, str):
        salt = salt.encode("utf-8")
    key = derive_key(encryption_key, salt)
    fernet = Fernet(key)
    decrypted = fernet.decrypt(encrypted_data["encrypted_token"].encode("utf-8"))
    return decrypted.decode("utf-8")
