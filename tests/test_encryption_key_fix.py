"""Tests for deployment fixes: encryption key validation, Docker defaults, and .env.example."""

from __future__ import annotations

import base64
import pytest
import os
import pathlib
from unittest.mock import AsyncMock, MagicMock, patch
from starlette.testclient import TestClient

from clickup_mcp.config import Settings, get_settings, validate_settings, validate_decoded_key
from clickup_mcp.app import create_app
from clickup_mcp.crypto import encrypt_token, decrypt_token, derive_key, _decode_key


def _make_key_32() -> str:
    """Generate a URL-safe base64 encoded 32-byte key."""
    return "l2G_gvqENw5Xdptya18vB8IyK7yEbZiLI4PtCP-6lGE"


def _make_key_16() -> str:
    """Generate a URL-safe base64 encoded 16-byte key."""
    return "me8oIy6lGBctWAPHudSKJg"


def _make_key_24() -> str:
    """Generate a URL-safe base64 encoded 24-byte key."""
    return "EhIRdKph9hjomdCAWML_IQr_euKo5TP1"


class TestEncryptionKeyValidation:
    """Tests for encryption key validation - decoded key length must be 16, 24, or 32 bytes."""

    def test_validate_decoded_key_32_bytes(self):
        """32-byte decoded key should pass validate_decoded_key."""
        key = _make_key_32()
        assert validate_decoded_key(key) is True
        assert len(_decode_key(key)) == 32

    def test_validate_decoded_key_16_bytes(self):
        """16-byte decoded key should pass validate_decoded_key."""
        key = _make_key_16()
        assert validate_decoded_key(key) is True
        assert len(_decode_key(key)) == 16

    def test_validate_decoded_key_24_bytes(self):
        """24-byte decoded key should pass validate_decoded_key."""
        key = _make_key_24()
        assert validate_decoded_key(key) is True
        assert len(_decode_key(key)) == 24

    def test_validate_decoded_key_invalid_length(self):
        """Decoded key with invalid length should fail validate_decoded_key."""
        # 8 bytes base64 = 12 chars
        key = "YWJjZGVmZ2g"  # "abcdefgh" (8 bytes)
        assert validate_decoded_key(key) is False

    def test_validate_decoded_key_empty_fails(self):
        """Empty key should fail validate_decoded_key."""
        assert validate_decoded_key("") is False

    def test_validate_decoded_key_invalid_base64_fails(self):
        """Invalid base64 should fail validate_decoded_key."""
        assert validate_decoded_key("!!!invalid!!!") is False

    def test_settings_accepts_any_non_empty_key(self):
        """Settings should accept any non-empty ENCRYPTION_KEY string."""
        s = Settings(ENCRYPTION_KEY=_make_key_32())
        assert validate_settings(s) is True

    def test_settings_rejects_empty_key(self):
        """Empty key should fail validate_settings."""
        s = Settings(ENCRYPTION_KEY="")
        assert validate_settings(s) is False

    def test_long_urlsafe_key_passes_validation(self):
        """URL-safe base64 encoded 32-byte key (43 chars) should pass validation."""
        key = _make_key_32()
        assert len(key) == 43
        s = Settings(ENCRYPTION_KEY=key)
        assert validate_settings(s) is True

    def test_unicode_key_passes(self):
        """Unicode keys should pass validation (any non-empty string accepted)."""
        s = Settings(ENCRYPTION_KEY="caf\u00e9-key-123")
        assert validate_settings(s) is True


class TestDockerfileDefaultKey:
    """Tests that the Dockerfile default encryption key is valid."""

    def test_dockerfile_env_key_is_non_empty(self):
        """The ENCRYPTION_KEY in Dockerfile should be non-empty."""
        dockerfile_path = pathlib.Path(__file__).parent.parent / "Dockerfile"
        content = dockerfile_path.read_text()

        for line in content.splitlines():
            if "ENCRYPTION_KEY=" in line and line.strip().startswith("ENCRYPTION_KEY="):
                line = line.rstrip("\\").strip()
                if "=" in line:
                    key_value = line.split("=", 1)[1].strip().strip('"').strip("'")
                    assert key_value != "", "Dockerfile key should not be empty"
                    break
        else:
            pytest.fail("ENCRYPTION_KEY not found in Dockerfile")

    def test_dockerfile_env_key_passes_validation(self):
        """The Dockerfile default encryption key should decode to valid length."""
        dockerfile_path = pathlib.Path(__file__).parent.parent / "Dockerfile"
        content = dockerfile_path.read_text()

        for line in content.splitlines():
            if "ENCRYPTION_KEY=" in line and line.strip().startswith("ENCRYPTION_KEY="):
                line = line.rstrip("\\").strip()
                if "=" in line:
                    key_value = line.split("=", 1)[1].strip().strip('"').strip("'")
                    assert validate_decoded_key(key_value), \
                        f"Key '{key_value}' did not decode to valid length"
                    break


class TestEnvExampleKey:
    """Tests that the .env.example file has a valid encryption key."""

    def test_env_example_key_is_non_empty(self):
        """The ENCRYPTION_KEY in .env.example should be non-empty."""
        env_example_path = pathlib.Path(__file__).parent.parent / ".env.example"
        content = env_example_path.read_text()

        for line in content.splitlines():
            if line.startswith("ENCRYPTION_KEY=") and not line.startswith("#"):
                key_value = line.split("=", 1)[1].strip()
                assert key_value != "your-32-byte-encryption-key-here", \
                    "Placeholder should be replaced with actual valid key"
                assert key_value != "", "Key should not be empty"
                break
        else:
            pytest.fail("ENCRYPTION_KEY not found in .env.example")

    def test_env_example_key_passes_validation(self):
        """The .env.example encryption key should decode to valid length."""
        env_example_path = pathlib.Path(__file__).parent.parent / ".env.example"
        content = env_example_path.read_text()

        for line in content.splitlines():
            if line.startswith("ENCRYPTION_KEY=") and not line.startswith("#"):
                key_value = line.split("=", 1)[1].strip()
                assert validate_decoded_key(key_value), \
                    f"Key '{key_value}' did not decode to valid length"
                break


class TestKeyDerivation:
    """Tests for key derivation functionality."""

    def test_derive_key_produces_fernet_key(self):
        """derive_key should produce a 44-char base64 key valid for Fernet."""
        key = _make_key_32()
        salt = b"test-salt-12345678"
        derived = derive_key(key, salt)
        # Fernet requires 32 bytes base64-encoded = 44 characters
        assert len(derived) == 44
        # Should be usable with Fernet
        from cryptography.fernet import Fernet
        fernet = Fernet(derived)
        assert fernet is not None

    def test_derive_key_is_deterministic(self):
        """Same key + salt should produce same derived key."""
        key = _make_key_32()
        salt = b"test-salt-12345678"
        derived1 = derive_key(key, salt)
        derived2 = derive_key(key, salt)
        assert derived1 == derived2

    def test_derive_key_different_salt(self):
        """Different salt should produce different derived key."""
        key = _make_key_32()
        derived1 = derive_key(key, b"salt123456789012")
        derived2 = derive_key(key, b"saltsaltsaltsalt")
        assert derived1 != derived2

    def test_derive_key_16_byte_key(self):
        """derive_key should work with 16-byte decoded key."""
        key = _make_key_16()
        derived = derive_key(key, b"salt123456789012")
        from cryptography.fernet import Fernet
        fernet = Fernet(derived)
        assert fernet is not None

    def test_derive_key_24_byte_key(self):
        """derive_key should work with 24-byte decoded key."""
        key = _make_key_24()
        derived = derive_key(key, b"salt123456789012")
        from cryptography.fernet import Fernet
        fernet = Fernet(derived)
        assert fernet is not None

    def test_decode_key_invalid_length_raises(self):
        """_decode_key should raise ValueError for invalid decoded lengths."""
        # "short" is 5 bytes when decoded - invalid
        with pytest.raises(ValueError, match="must be 16, 24, or 32 bytes"):
            _decode_key("c2hvcnQ")  # "short" = 5 bytes


class TestEncryptionWithBase64Keys:
    """Tests for encryption/decryption with URL-safe base64 encoded keys."""

    def test_encrypt_decrypt_32_byte_key(self):
        """Encryption should work with 32-byte decoded key."""
        key = _make_key_32()
        token = "test-token"
        encrypted = encrypt_token(token, key, "user-1")
        decrypted = decrypt_token(encrypted, key, "user-1")
        assert decrypted == token

    def test_encrypt_decrypt_16_byte_key(self):
        """Encryption should work with 16-byte decoded key."""
        key = _make_key_16()
        token = "test-token"
        encrypted = encrypt_token(token, key, "user-1")
        decrypted = decrypt_token(encrypted, key, "user-1")
        assert decrypted == token

    def test_encrypt_decrypt_24_byte_key(self):
        """Encryption should work with 24-byte decoded key."""
        key = _make_key_24()
        token = "test-token"
        encrypted = encrypt_token(token, key, "user-1")
        decrypted = decrypt_token(encrypted, key, "user-1")
        assert decrypted == token

    def test_encrypt_decrypt_dockerfile_key(self):
        """Encryption should work with the Dockerfile default key."""
        dockerfile_path = pathlib.Path(__file__).parent.parent / "Dockerfile"
        content = dockerfile_path.read_text()
        docker_key = None
        for line in content.splitlines():
            if "ENCRYPTION_KEY=" in line and line.strip().startswith("ENCRYPTION_KEY="):
                line = line.rstrip("\\").strip()
                if "=" in line:
                    docker_key = line.split("=", 1)[1].strip().strip('"').strip("'")
                    break
        assert docker_key is not None
        token = "test-token-for-docker-key"
        encrypted = encrypt_token(token, docker_key, "user-1")
        decrypted = decrypt_token(encrypted, docker_key, "user-1")
        assert decrypted == token

    def test_encrypt_decrypt_oauth_token(self):
        """Encryption should work with OAuth token content."""
        key = _make_key_32()
        token = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.oauth.refresh"
        encrypted = encrypt_token(token, key, "user-1")
        decrypted = decrypt_token(encrypted, key, "user-1")
        assert decrypted == token

    def test_encrypt_decrypt_empty_token(self):
        """Encryption should work with empty token."""
        key = _make_key_32()
        encrypted = encrypt_token("", key, "user-1")
        decrypted = decrypt_token(encrypted, key, "user-1")
        assert decrypted == ""

    def test_encrypt_decrypt_long_token(self):
        """Encryption should work with long token."""
        key = _make_key_32()
        token = "x" * 500
        encrypted = encrypt_token(token, key, "user-1")
        decrypted = decrypt_token(encrypted, key, "user-1")
        assert decrypted == token


class TestAppStartupWithKey:
    """Tests that the app starts correctly with valid encryption keys."""

    def test_app_starts_with_valid_32_byte_key(self):
        """App should start with valid 32-byte decryption key."""
        mock_client = MagicMock()
        mock_db = MagicMock()
        mock_collection = MagicMock()
        mock_oauth = MagicMock()
        mock_session = MagicMock()
        mock_db.__getitem__ = MagicMock(side_effect=lambda key: {
            "api_tokens": mock_collection,
            "oauth_tokens": mock_oauth,
            "oauth_sessions": mock_session,
        }.get(key, MagicMock()))
        mock_client.__getitem__ = MagicMock(return_value=mock_db)
        with patch("clickup_mcp.storage.MongoClient", return_value=mock_client):
            settings = Settings(
                CLICKUP_API_TOKEN="test-token",
                ENCRYPTION_KEY=_make_key_32(),
            )
            app = create_app(settings)
            assert app is not None

    def test_app_starts_with_valid_16_byte_key(self):
        """App should start with valid 16-byte decryption key."""
        mock_client = MagicMock()
        mock_db = MagicMock()
        mock_collection = MagicMock()
        mock_oauth = MagicMock()
        mock_session = MagicMock()
        mock_db.__getitem__ = MagicMock(side_effect=lambda key: {
            "api_tokens": mock_collection,
            "oauth_tokens": mock_oauth,
            "oauth_sessions": mock_session,
        }.get(key, MagicMock()))
        mock_client.__getitem__ = MagicMock(return_value=mock_db)
        with patch("clickup_mcp.storage.MongoClient", return_value=mock_client):
            settings = Settings(
                CLICKUP_API_TOKEN="test-token",
                ENCRYPTION_KEY=_make_key_16(),
            )
            app = create_app(settings)
            assert app is not None

    def test_app_starts_with_valid_24_byte_key(self):
        """App should start with valid 24-byte decryption key."""
        mock_client = MagicMock()
        mock_db = MagicMock()
        mock_collection = MagicMock()
        mock_oauth = MagicMock()
        mock_session = MagicMock()
        mock_db.__getitem__ = MagicMock(side_effect=lambda key: {
            "api_tokens": mock_collection,
            "oauth_tokens": mock_oauth,
            "oauth_sessions": mock_session,
        }.get(key, MagicMock()))
        mock_client.__getitem__ = MagicMock(return_value=mock_db)
        with patch("clickup_mcp.storage.MongoClient", return_value=mock_client):
            settings = Settings(
                CLICKUP_API_TOKEN="test-token",
                ENCRYPTION_KEY=_make_key_24(),
            )
            app = create_app(settings)
            assert app is not None

    def test_app_starts_with_dockerfile_key(self):
        """App should start with Dockerfile default key."""
        mock_client = MagicMock()
        mock_db = MagicMock()
        mock_collection = MagicMock()
        mock_oauth = MagicMock()
        mock_session = MagicMock()
        mock_db.__getitem__ = MagicMock(side_effect=lambda key: {
            "api_tokens": mock_collection,
            "oauth_tokens": mock_oauth,
            "oauth_sessions": mock_session,
        }.get(key, MagicMock()))
        mock_client.__getitem__ = MagicMock(return_value=mock_db)
        with patch("clickup_mcp.storage.MongoClient", return_value=mock_client):
            dockerfile_path = pathlib.Path(__file__).parent.parent / "Dockerfile"
            content = dockerfile_path.read_text()
            docker_key = None
            for line in content.splitlines():
                if "ENCRYPTION_KEY=" in line and line.strip().startswith("ENCRYPTION_KEY="):
                    line = line.rstrip("\\").strip()
                    if "=" in line:
                        docker_key = line.split("=", 1)[1].strip().strip('"').strip("'")
                        break
            assert docker_key is not None
            settings = Settings(
                CLICKUP_API_TOKEN="test-token",
                ENCRYPTION_KEY=docker_key,
            )
            app = create_app(settings)
            assert app is not None


class TestSecretsNotExposed:
    """Tests that secrets are not exposed in error responses or logs."""

    def test_encrypted_token_not_in_string(self):
        """Encrypted tokens should not appear as plaintext in strings."""
        key = _make_key_32()
        token = "super-secret-api-token"
        encrypted = encrypt_token(token, key, "user-1")
        # The encrypted data should not contain the original token
        assert token not in encrypted["encrypted_token"]
        assert token not in encrypted.get("salt", "")

    def test_encrypted_output_is_different(self):
        """Each encryption should produce unique output."""
        key = _make_key_32()
        token = "same-token"
        enc1 = encrypt_token(token, key, "user-1")
        enc2 = encrypt_token(token, key, "user-1")
        assert enc1["encrypted_token"] != enc2["encrypted_token"]

    def test_different_personas_different_encrypted(self):
        """Different personas should produce different encrypted output."""
        key = _make_key_32()
        token = "same-token"
        enc1 = encrypt_token(token, key, "persona-a")
        enc2 = encrypt_token(token, key, "persona-b")
        assert enc1["encrypted_token"] != enc2["encrypted_token"]


class TestEnvironmentVariableDefaults:
    """Tests for environment variable defaults and configuration."""

    def test_settings_default_app_name(self):
        """APP_NAME should default to ClickUpMCP."""
        s = Settings(ENCRYPTION_KEY=_make_key_32())
        assert s.APP_NAME == "ClickUpMCP"

    def test_settings_default_description(self):
        """APP_DESCRIPTION should have the correct default."""
        s = Settings(ENCRYPTION_KEY=_make_key_32())
        assert s.APP_DESCRIPTION == "Integrates ClickUp tasks, spaces, lists, and updates."

    def test_settings_default_version(self):
        """VERSION should default to 1.0.0."""
        s = Settings(ENCRYPTION_KEY=_make_key_32())
        assert s.VERSION == "1.0.0"

    def test_settings_default_host(self):
        """HOST should default to 0.0.0.0."""
        s = Settings(ENCRYPTION_KEY=_make_key_32())
        assert s.HOST == "0.0.0.0"

    def test_settings_default_port(self):
        """PORT should default to 8000."""
        s = Settings(ENCRYPTION_KEY=_make_key_32())
        assert s.PORT == 8000

    def test_settings_default_mongodb_uri(self):
        """MONGODB_URI should default to local MongoDB."""
        s = Settings(ENCRYPTION_KEY=_make_key_32())
        assert s.MONGODB_URI == "mongodb://localhost:27017"

    def test_settings_default_mongodb_db_name(self):
        """MONGODB_DB_NAME should default to clickup_mcp."""
        s = Settings(ENCRYPTION_KEY=_make_key_32())
        assert s.MONGODB_DB_NAME == "clickup_mcp"

    def test_settings_default_mongodb_collection(self):
        """MONGODB_COLLECTION should default to api_tokens."""
        s = Settings(ENCRYPTION_KEY=_make_key_32())
        assert s.MONGODB_COLLECTION == "api_tokens"

    def test_settings_default_mongodb_oauth_collection(self):
        """MONGODB_OAUTH_COLLECTION should default to oauth_tokens."""
        s = Settings(ENCRYPTION_KEY=_make_key_32())
        assert s.MONGODB_OAUTH_COLLECTION == "oauth_tokens"

    def test_settings_default_mongodb_session_collection(self):
        """MONGODB_SESSION_COLLECTION should default to oauth_sessions."""
        s = Settings(ENCRYPTION_KEY=_make_key_32())
        assert s.MONGODB_SESSION_COLLECTION == "oauth_sessions"

    def test_settings_default_cors_origins(self):
        """CORS_ORIGINS should default to *."""
        s = Settings(ENCRYPTION_KEY=_make_key_32())
        assert s.CORS_ORIGINS == "*"

    def test_settings_default_persona_header(self):
        """PERSONA_HEADER should default to X-Persona-ID."""
        s = Settings(ENCRYPTION_KEY=_make_key_32())
        assert s.PERSONA_HEADER == "X-Persona-ID"

    def test_settings_default_clickup_base_url(self):
        """CLICKUP_API_BASE should default to ClickUp API v2."""
        s = Settings(ENCRYPTION_KEY=_make_key_32())
        assert s.CLICKUP_API_BASE == "https://api.clickup.com/api/v2"

    def test_settings_default_oauth_base_url(self):
        """CLICKUP_OAUTH_AUTH_BASE_URL should default to app.clickup.com."""
        s = Settings(ENCRYPTION_KEY=_make_key_32())
        assert s.CLICKUP_OAUTH_AUTH_BASE_URL == "https://app.clickup.com"

    def test_settings_default_oauth_token_url(self):
        """CLICKUP_OAUTH_TOKEN_URL should default to ClickUp OAuth token URL."""
        s = Settings(ENCRYPTION_KEY=_make_key_32())
        assert s.CLICKUP_OAUTH_TOKEN_URL == "https://api.clickup.com/api/v2/oauth/token"

    def test_settings_default_oauth_scopes(self):
        """CLICKUP_OAUTH_SCOPES should default to 'open'."""
        s = Settings(ENCRYPTION_KEY=_make_key_32())
        assert s.CLICKUP_OAUTH_SCOPES == "open"
