from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from starlette.testclient import TestClient

from clickup_mcp.config import Settings
from clickup_mcp.app import create_app
from clickup_mcp.crypto import encrypt_token


def _make_oauth_settings(**overrides) -> Settings:
    base = {
        "CLICKUP_API_TOKEN": "test-api-token",
        "ENCRYPTION_KEY": "l2G_gvqENw5Xdptya18vB8IyK7yEbZiLI4PtCP-6lGE",
        "MONGODB_URI": "mongodb://localhost:27017",
        "CLICKUP_OAUTH_CLIENT_ID": "test-client-id",
        "CLICKUP_OAUTH_CLIENT_SECRET": "test-client-secret",
        "CLICKUP_OAUTH_REDIRECT_URI": "http://localhost:8000/auth/callback",
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


class TestAuthLogoutFixed:
    """Tests for the fixed logout endpoint that properly iterates workspaces."""

    def test_logout_all_workspaces_iterates_tokens(self):
        """Logout without workspace_id should iterate over all stored tokens."""
        mock_client, mock_db, mock_collection, mock_oauth, mock_session = _make_mock_mongodb()
        mock_collection.get_all_tokens = AsyncMock(return_value=[
            {"workspace_id": "ws-1"},
            {"workspace_id": "ws-2"},
        ])
        mock_collection.delete_one = MagicMock(return_value=MagicMock(deleted_count=1))
        mock_oauth.delete_many = MagicMock(return_value=MagicMock(deleted_count=0))
        with patch("clickup_mcp.storage.MongoClient", return_value=mock_client):
            settings = _make_oauth_settings()
            app = create_app(settings)
            client = TestClient(app)
            resp = client.post(
                "/auth/logout",
                json={},
                headers={"X-Persona-ID": "test-persona"},
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["status"] == "logged_out"
            assert "oauth_tokens_revoked" in data


class TestUiConfigWithPersona:
    """Tests for ui/config endpoint using persona header."""

    def test_ui_config_uses_person_header(self):
        """ui/config should use X-Persona-ID header, not hardcoded 'anonymous'."""
        mock_client, mock_db, mock_collection, mock_oauth, mock_session = _make_mock_mongodb()
        with patch("clickup_mcp.storage.TokenStore.get_all_tokens", new_callable=AsyncMock) as mock_tokens:
            mock_tokens.return_value = [
                {"workspace_id": "ws-persona-a"},
            ]
            with patch("clickup_mcp.storage.MongoClient", return_value=mock_client):
                settings = _make_oauth_settings()
                app = create_app(settings)
                client = TestClient(app)
                resp = client.get(
                    "/ui/config",
                    headers={"X-Persona-ID": "persona-a"},
                )
                assert resp.status_code == 200
                data = resp.json()
                assert "workspaces" in data
                assert len(data["workspaces"]) == 1
                assert data["workspaces"][0]["workspace_id"] == "ws-persona-a"

    def test_ui_config_empty_for_unknown_persona(self):
        """ui/config should return empty workspaces for persona with no connections."""
        mock_client, mock_db, mock_collection, mock_oauth, mock_session = _make_mock_mongodb()
        mock_collection.get_all_tokens = AsyncMock(return_value=[])
        with patch("clickup_mcp.storage.MongoClient", return_value=mock_client):
            settings = _make_oauth_settings()
            app = create_app(settings)
            client = TestClient(app)
            resp = client.get(
                "/ui/config",
                headers={"X-Persona-ID": "unknown-persona"},
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["workspaces"] == []


class TestResponsesAnyImport:
    """Tests for the oauth_error_response function with Any type."""

    def test_oauth_error_response_structure(self):
        """oauth_error_response should return properly structured JSON."""
        from clickup_mcp.responses import oauth_error_response
        resp = oauth_error_response("invalid_grant", "The authorization code is invalid")
        assert resp.status_code == 400
        assert resp.media_type == "application/json"
        body = resp.body.decode("utf-8")
        assert "invalid_grant" in body
        assert "authorization code is invalid" in body

    def test_oauth_error_response_minimal(self):
        """oauth_error_response with only error code should work."""
        from clickup_mcp.responses import oauth_error_response
        resp = oauth_error_response("access_denied")
        assert resp.status_code == 400
        body = resp.body.decode("utf-8")
        assert "access_denied" in body

    def test_oauth_error_response_custom_status(self):
        """oauth_error_response should support custom status codes."""
        from clickup_mcp.responses import oauth_error_response
        resp = oauth_error_response("server_error", "Internal error", 500)
        assert resp.status_code == 500


class TestOAuth2ConfigValidation:
    """Tests for OAuth2 configuration validation edge cases."""

    def test_oauth_configured_detection(self):
        """manifest should detect OAuth2 when client_id is set."""
        from clickup_mcp.responses import manifest_response
        s = Settings(
            ENCRYPTION_KEY="l2G_gvqENw5Xdptya18vB8IyK7yEbZiLI4PtCP-6lGE",
            CLICKUP_OAUTH_CLIENT_ID="client-id",
            CLICKUP_OAUTH_CLIENT_SECRET="client-secret",
        )
        manifest = manifest_response(s)
        assert manifest["auth"]["type"] == "oauth2"
        assert manifest["auth"]["flow"] == "authorization_code"

    def test_oauth_not_configured_detection(self):
        """manifest should detect token auth when OAuth2 is not configured."""
        from clickup_mcp.responses import manifest_response
        s = Settings(
            ENCRYPTION_KEY="l2G_gvqENw5Xdptya18vB8IyK7yEbZiLI4PtCP-6lGE",
            CLICKUP_OAUTH_CLIENT_ID="",
            CLICKUP_OAUTH_CLIENT_SECRET="",
        )
        manifest = manifest_response(s)
        assert manifest["auth"]["type"] == "token"
        assert manifest["auth"]["flow"] == "bearer"

    def test_oauth_scopes_handling(self):
        """OAuth scopes should be properly split from comma-separated string."""
        from clickup_mcp.responses import manifest_response
        s = Settings(
            ENCRYPTION_KEY="l2G_gvqENw5Xdptya18vB8IyK7yEbZiLI4PtCP-6lGE",
            CLICKUP_OAUTH_CLIENT_ID="client-id",
            CLICKUP_OAUTH_CLIENT_SECRET="client-secret",
            CLICKUP_OAUTH_SCOPES="open,read,write",
        )
        manifest = manifest_response(s)
        assert manifest["auth"]["scopes"] == ["open", "read", "write"]
