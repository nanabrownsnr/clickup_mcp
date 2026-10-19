from __future__ import annotations

import pytest
from clickup_mcp.crypto import encrypt_token, decrypt_token
from clickup_mcp.config import validate_decoded_key


def _key_32() -> str:
    """URL-safe base64 encoded 32-byte key."""
    return "l2G_gvqENw5Xdptya18vB8IyK7yEbZiLI4PtCP-6lGE"


def _key_16() -> str:
    """URL-safe base64 encoded 16-byte key."""
    return "me8oIy6lGBctWAPHudSKJg"


def _key_24() -> str:
    """URL-safe base64 encoded 24-byte key."""
    return "EhIRdKph9hjomdCAWML_IQr_euKo5TP1"


class TestCrypto:
    def test_encrypt_decrypt_roundtrip_32_byte_key(self):
        key = _key_32()
        persona = "user-123"
        token = "secret-oauth-token-abc123"

        encrypted = encrypt_token(token, key, persona)
        assert "encrypted_token" in encrypted
        assert "salt" in encrypted
        assert encrypted["encrypted_token"] != token

        decrypted = decrypt_token(encrypted, key, persona)
        assert decrypted == token

    def test_encrypt_decrypt_roundtrip_16_byte_key(self):
        key = _key_16()
        persona = "user-123"
        token = "secret-oauth-token-abc123"

        encrypted = encrypt_token(token, key, persona)
        decrypted = decrypt_token(encrypted, key, persona)
        assert decrypted == token

    def test_encrypt_decrypt_roundtrip_24_byte_key(self):
        key = _key_24()
        persona = "user-123"
        token = "secret-oauth-token-abc123"

        encrypted = encrypt_token(token, key, persona)
        decrypted = decrypt_token(encrypted, key, persona)
        assert decrypted == token

    def test_different_personas_produce_different_encrypted(self):
        key = _key_32()
        token = "secret-oauth-token-abc123"

        enc1 = encrypt_token(token, key, "persona-a")
        enc2 = encrypt_token(token, key, "persona-b")

        assert enc1["encrypted_token"] != enc2["encrypted_token"]

    def test_decrypt_with_wrong_encryption_key_fails(self):
        persona = "persona-a"
        token = "secret-token"

        key = _key_32()
        encrypted = encrypt_token(token, key, persona)

        # Different key should fail to decrypt
        other_key = "m8oIy6lGBctWAPHudSKJgZ"
        with pytest.raises(Exception):
            decrypt_token(encrypted, other_key, persona)

    def test_empty_token(self):
        key = _key_32()
        persona = "user"

        encrypted = encrypt_token("", key, persona)
        decrypted = decrypt_token(encrypted, key, persona)
        assert decrypted == ""

    def test_long_token(self):
        key = _key_32()
        persona = "user"
        token = "x" * 500

        encrypted = encrypt_token(token, key, persona)
        decrypted = decrypt_token(encrypted, key, persona)
        assert decrypted == token

    def test_encrypted_output_is_not_plaintext(self):
        key = _key_32()
        persona = "user"
        token = "my-access-token"

        encrypted = encrypt_token(token, key, persona)
        assert token not in encrypted["encrypted_token"]

    def test_validate_decoded_key_true_for_valid(self):
        assert validate_decoded_key(_key_32()) is True
        assert validate_decoded_key(_key_16()) is True
        assert validate_decoded_key(_key_24()) is True

    def test_validate_decoded_key_false_for_invalid(self):
        assert validate_decoded_key("") is False
        assert validate_decoded_key("short") is False
        assert validate_decoded_key("!!!invalid!!!") is False
