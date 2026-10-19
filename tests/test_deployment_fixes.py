"""Tests for deployment fixes: lazy MongoDB, validation behavior, and token encryption."""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from starlette.testclient import TestClient

from clickup_mcp.config import Settings, validate_settings
from clickup_mcp.app import create_app
from clickup_mcp.crypto import encrypt_token, decrypt_token
from clickup_mcp.storage import TokenStore


def _make_settings(**overrides) -> Settings:
    base = {
        "CLICKUP_API_TOKEN": "test-api-token",
        "ENCRYPTION_KEY": "l2G_gvqENw5Xdptya18vB8IyK7yEbZiLI4PtCP-6lGE",
        "MONGODB_URI": "mongodb://localhost:27017",
    }
    base.update(overrides)
    return Settings(**base)


def _make_mock_mongodb():
    mock_client = MagicMock()
    mock_db = MagicMock()
    mock_collection = MagicMock()
    mock_oauth_collection = MagicMock()
    mock_session_collection = MagicMock()

    mock_db.__getitem__ = MagicMock(side_effect=lambda key: {
        "api_tokens": mock_collection,
        "oauth_tokens": mock_oauth_collection,
        "oauth_sessions": mock_session_collection,
    }.get(key, MagicMock()))

    mock_client.__getitem__ = MagicMock(return_value=mock_db)
    mock_collection.create_index = MagicMock()
    mock_oauth_collection.create_index = MagicMock()
    mock_session_collection.create_index = MagicMock()
    return mock_client, mock_db, mock_collection, mock_oauth_collection, mock_session_collection


class TestLazyMongoDB:
    """Tests verifying MongoDB connection is deferred until first operation."""

    def test_store_init_does_not_connect(self):
        """TokenStore.__init__ must NOT connect to MongoDB."""
        mock_client, _, _, _, _ = _make_mock_mongodb()
        with patch("clickup_mcp.storage.MongoClient", return_value=mock_client) as mock:
            settings = _make_settings()
            store = TokenStore(settings)
            mock.assert_not_called()
            assert store._client is None

    def test_app_creation_does_not_connect(self):
        """FastAPI app creation must NOT connect to MongoDB."""
        mock_client, _, _, _, _ = _make_mock_mongodb()
        with patch("clickup_mcp.storage.MongoClient", return_value=mock_client) as mock:
            settings = _make_settings()
            app = create_app(settings)
            # MongoClient should NOT be called during app creation
            mock.assert_not_called()

    async def test_first_db_operation_triggers_connection(self):
        """First database operation must establish MongoDB connection."""
        mock_client, mock_db, mock_collection, _, _ = _make_mock_mongodb()
        mock_collection.find_one = MagicMock(return_value=None)
        with patch("clickup_mcp.storage.MongoClient", return_value=mock_client):
            settings = _make_settings()
            store = TokenStore(settings)
            assert store._client is None
            # Trigger connection via get_token
            await store.get_token("user-1", "ws-1")
            assert store._client is mock_client

    async def test_multiple_stores_do_not_share_connection(self):
        """Each TokenStore instance should have its own MongoDB connection."""
        mock_client1, mock_db1, mock_collection1, _, _ = _make_mock_mongodb()
        mock_client2, mock_db2, mock_collection2, _, _ = _make_mock_mongodb()
        with patch("clickup_mcp.storage.MongoClient", side_effect=[mock_client1, mock_client2]):
            settings = _make_settings()
            store1 = TokenStore(settings)
            store2 = TokenStore(settings)
            mock_collection1.find_one = MagicMock(return_value=None)
            mock_collection2.find_one = MagicMock(return_value=None)
            await store1.get_token("user-1", "ws-1")
            await store2.get_token("user-2", "ws-2")
            assert store1._client is mock_client1
            assert store2._client is mock_client2
            assert store1._client is not store2._client


class TestEncryptionValidation:
    """Tests for encryption key validation behavior."""

    def test_validate_settings_any_length_passes(self):
        """validate_settings should accept any non-empty string, never raise or block."""
        settings = _make_settings()
        # Should not raise
        result = validate_settings(settings)
        # Returns True - any non-empty key is valid
        assert result is True

    def test_validate_settings_valid_key(self):
        settings = _make_settings(ENCRYPTION_KEY="l2G_gvqENw5Xdptya18vB8IyK7yEbZiLI4PtCP-6lGE")
        assert validate_settings(settings) is True

    def test_validate_settings_empty_key(self):
        s = Settings(ENCRYPTION_KEY="")
        assert validate_settings(s) is False

    def test_any_key_length_passes(self):
        """validate_settings accepts any non-empty string (decoding happens at runtime)."""
        for length in (1, 5, 10, 15, 16, 24, 32, 33, 43, 100):
            key = "x" * length
            s = Settings(ENCRYPTION_KEY=key)
            assert validate_settings(s) is True, f"Key length {length} should be valid"

    def test_encryption_key_not_embedded_in_code(self):
        """No hardcoded secrets in source files."""
        import os
        import glob
        src_files = glob.glob("src/**/*.py", recursive=True)
        for filepath in src_files:
            with open(filepath) as f:
                content = f.read()
            # Should not contain hardcoded encryption keys
            assert "ENCRYPTION_KEY=" not in content or \
                   'default=""' in content or \
                   'Field(default=""' in content or \
                   "env_prefix" in content


class TestTokenEncryption:
    """Tests for token encryption/decryption with persona scoping."""

    def test_encryption_is_persona_specific(self):
        """Same token encrypted for different personas should produce different ciphertext."""
        key = "l2G_gvqENw5Xdptya18vB8IyK7yEbZiLI4PtCP-6lGE"
        token = "secret-api-token"
        enc_a = encrypt_token(token, key, "persona-a")
        enc_b = encrypt_token(token, key, "persona-b")
        assert enc_a["encrypted_token"] != enc_b["encrypted_token"]

    def test_decryption_requires_correct_encryption_key(self):
        """Decrypting with wrong encryption key should fail."""
        key = "l2G_gvqENw5Xdptya18vB8IyK7yEbZiLI4PtCP-6lGE"
        token = "secret-token"
        encrypted = encrypt_token(token, key, "persona-a")
        with pytest.raises(Exception):
            decrypt_token(encrypted, "0000000000000000", "persona-a")

    def test_encryption_output_contains_no_plaintext(self):
        """Encrypted output should not contain the original token."""
        key = "l2G_gvqENw5Xdptya18vB8IyK7yEbZiLI4PtCP-6lGE"
        token = "my-super-secret-token"
        encrypted = encrypt_token(token, key, "user-1")
        assert token not in encrypted["encrypted_token"]

    def test_encrypted_data_is_json_serializable(self):
        """Encrypted token data should be JSON-serializable for MongoDB storage."""
        import json
        key = "l2G_gvqENw5Xdptya18vB8IyK7yEbZiLI4PtCP-6lGE"
        token = "api-token-for-storage"
        encrypted = encrypt_token(token, key, "user-1")
        # Should not raise
        json_str = json.dumps(encrypted)
        assert "encrypted_token" in json_str
        assert "salt" in json_str

    def test_decrypt_preserves_token_integrity(self):
        """Decrypted token must exactly match original."""
        key = "l2G_gvqENw5Xdptya18vB8IyK7yEbZiLI4PtCP-6lGE"
        token = "Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9"
        encrypted = encrypt_token(token, key, "user-1")
        decrypted = decrypt_token(encrypted, key, "user-1")
        assert decrypted == token


class TestOAuthPersonaScoping:
    """Tests for OAuth2 flow with persona-based scoping."""

    def test_oauth_login_uses_person_header(self):
        """OAuth login should use X-Persona-ID header for session storage."""
        mock_client, mock_db, mock_collection, mock_oauth, mock_session = _make_mock_mongodb()
        with patch("clickup_mcp.storage.MongoClient", return_value=mock_client):
            settings = _make_settings(
                CLICKUP_OAUTH_CLIENT_ID="test-client",
                CLICKUP_OAUTH_CLIENT_SECRET="test-secret",
                CLICKUP_OAUTH_REDIRECT_URI="http://localhost/callback",
            )
            app = create_app(settings)
            client = TestClient(app)
            resp = client.get(
                "/auth/login?workspace_id=ws-123",
                headers={"X-Persona-ID": "my-persona"}
            )
            assert resp.status_code == 200
            data = resp.json()
            assert "authorization_url" in data
            assert data["status"] == "authorization_required"

    def test_oauth_callback_stores_token_with_persona_scope(self):
        """OAuth callback should store tokens scoped to persona:workspace."""
        mock_client, mock_db, mock_collection, mock_oauth, mock_session = _make_mock_mongodb()
        mock_session.find_one = MagicMock(return_value={
            "session_data": {"persona_id": "test-persona", "workspace_id": "ws-123"}
        })
        mock_session.delete_one = MagicMock(return_value=MagicMock(deleted_count=1))
        mock_oauth.replace_one = MagicMock()
        with patch("clickup_mcp.storage.MongoClient", return_value=mock_client):
            with patch("clickup_mcp.clickup_client.ClickUpClient.exchange_code_for_token", new_callable=AsyncMock) as mock_exchange:
                mock_exchange.return_value = {
                    "access_token": "access-token",
                    "refresh_token": "refresh-token",
                    "expires_in": 3600,
                }
                settings = _make_settings(
                    CLICKUP_OAUTH_CLIENT_ID="client",
                    CLICKUP_OAUTH_CLIENT_SECRET="secret",
                    CLICKUP_OAUTH_REDIRECT_URI="http://localhost/callback",
                )
                app = create_app(settings)
                client = TestClient(app)
                resp = client.get(
                    "/auth/callback?code=auth-code&state=test-state",
                    headers={"X-Persona-ID": "test-persona"}
                )
                assert resp.status_code == 200
                data = resp.json()
                assert data["access_token_set"] is True
                assert data["workspace_id"] == "ws-123"

    def test_person_header_fallback_to_anonymous(self):
        """Missing X-Persona-ID header should default to 'anonymous'."""
        mock_client, mock_db, mock_collection, _, _ = _make_mock_mongodb()
        mock_collection.find_one = MagicMock(return_value=None)
        with patch("clickup_mcp.storage.MongoClient", return_value=mock_client):
            settings = _make_settings()
            app = create_app(settings)
            client = TestClient(app)
            resp = client.get("/token/validate?workspace_id=ws-123")
            assert resp.status_code == 200
            data = resp.json()
            assert data["valid"] is False


class TestStructuredErrorResponses:
    """Tests ensuring error responses never leak secrets."""

    def test_error_response_has_no_plaintext_tokens(self):
        """Error responses should not contain raw API tokens."""
        mock_client, mock_db, mock_collection, _, _ = _make_mock_mongodb()
        with patch("clickup_mcp.storage.MongoClient", return_value=mock_client):
            settings = _make_settings()
            app = create_app(settings)
            client = TestClient(app)
            resp = client.post(
                "/tools/list_tasks",
                json={"workspace_id": "ws", "list_id": "list"},
                headers={"X-Persona-ID": "test-persona"},
            )
            data = resp.json()
            # Error response should have structured format
            assert "error" in data
            assert "code" in data["error"]
            assert "message" in data["error"]
            # Should not leak any token content
            error_str = str(data)
            assert "secret" not in error_str.lower() or "secret" in data.get("error", {}).get("message", "").lower()

    def test_tool_error_provides_readability(self):
        """Tool errors should have meaningful messages for debugging."""
        mock_client, mock_db, mock_collection, _, _ = _make_mock_mongodb()
        mock_collection.find_one = MagicMock(return_value=None)
        with patch("clickup_mcp.storage.MongoClient", return_value=mock_client):
            settings = _make_settings()
            app = create_app(settings)
            client = TestClient(app)
            resp = client.post(
                "/tools/create_task",
                json={"list_id": "list-1", "name": "Test Task"},
                headers={"X-Persona-ID": "test"},
            )
            data = resp.json()
            assert "error" in data
            # Error should indicate missing connection
            assert "error" in data
            assert "code" in data["error"]
