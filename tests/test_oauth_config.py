from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from clickup_mcp.config import Settings


class TestOAuth2Settings:
    def test_oauth_defaults(self):
        s = Settings(
            ENCRYPTION_KEY="l2G_gvqENw5Xdptya18vB8IyK7yEbZiLI4PtCP-6lGE",
        )
        assert s.CLICKUP_OAUTH_CLIENT_ID == ""
        assert s.CLICKUP_OAUTH_CLIENT_SECRET == ""
        assert s.CLICKUP_OAUTH_REDIRECT_URI == ""
        assert s.CLICKUP_OAUTH_AUTH_BASE_URL == "https://app.clickup.com"
        assert s.CLICKUP_OAUTH_TOKEN_URL == "https://api.clickup.com/api/v2/oauth/token"
        assert s.CLICKUP_OAUTH_REVOKE_URL == "https://api.clickup.com/api/v2/oauth/revoke"
        assert s.CLICKUP_OAUTH_SCOPES == "open"
        assert s.MONGODB_OAUTH_COLLECTION == "oauth_tokens"
        assert s.MONGODB_SESSION_COLLECTION == "oauth_sessions"

    def test_oauth_configured(self):
        s = Settings(
            ENCRYPTION_KEY="l2G_gvqENw5Xdptya18vB8IyK7yEbZiLI4PtCP-6lGE",
            CLICKUP_OAUTH_CLIENT_ID="test-client-id",
            CLICKUP_OAUTH_CLIENT_SECRET="test-client-secret",
            CLICKUP_OAUTH_REDIRECT_URI="http://localhost:8000/auth/callback",
        )
        assert s.CLICKUP_OAUTH_CLIENT_ID == "test-client-id"
        assert s.CLICKUP_OAUTH_CLIENT_SECRET == "test-client-secret"
        assert s.CLICKUP_OAUTH_REDIRECT_URI == "http://localhost:8000/auth/callback"

    def test_oauth_scopes_split(self):
        s = Settings(
            ENCRYPTION_KEY="l2G_gvqENw5Xdptya18vB8IyK7yEbZiLI4PtCP-6lGE",
            CLICKUP_OAUTH_CLIENT_ID="test",
            CLICKUP_OAUTH_CLIENT_SECRET="test",
            CLICKUP_OAUTH_SCOPES="open,read,write",
        )
        scopes = s.CLICKUP_OAUTH_SCOPES.split(",")
        assert scopes == ["open", "read", "write"]


class TestOAuth2ConfigValidation:
    def test_validate_with_oauth_enabled(self):
        s = Settings(
            CLICKUP_API_TOKEN="",
            ENCRYPTION_KEY="l2G_gvqENw5Xdptya18vB8IyK7yEbZiLI4PtCP-6lGE",
            CLICKUP_OAUTH_CLIENT_ID="client-id",
            CLICKUP_OAUTH_CLIENT_SECRET="client-secret",
        )
        from clickup_mcp.config import validate_settings
        result = validate_settings(s)
        assert result is True

    def test_validate_with_oauth_missing_secret(self):
        s = Settings(
            CLICKUP_API_TOKEN="",
            ENCRYPTION_KEY="l2G_gvqENw5Xdptya18vB8IyK7yEbZiLI4PtCP-6lGE",
            CLICKUP_OAUTH_CLIENT_ID="client-id",
            CLICKUP_OAUTH_CLIENT_SECRET="",
        )
        from clickup_mcp.config import validate_settings
        result = validate_settings(s)
        assert result is True


class TestManifestOAuth2:
    def test_manifest_without_oauth(self):
        from clickup_mcp.responses import manifest_response
        s = Settings(ENCRYPTION_KEY="l2G_gvqENw5Xdptya18vB8IyK7yEbZiLI4PtCP-6lGE")
        manifest = manifest_response(s)
        assert manifest["auth"]["type"] == "token"
        assert manifest["auth"]["flow"] == "bearer"

    def test_manifest_with_oauth(self):
        from clickup_mcp.responses import manifest_response
        s = Settings(
            ENCRYPTION_KEY="l2G_gvqENw5Xdptya18vB8IyK7yEbZiLI4PtCP-6lGE",
            CLICKUP_OAUTH_CLIENT_ID="test-client-id",
            CLICKUP_OAUTH_CLIENT_SECRET="test-secret",
        )
        manifest = manifest_response(s)
        assert manifest["auth"]["type"] == "oauth2"
        assert manifest["auth"]["flow"] == "authorization_code"
        assert "open" in manifest["auth"]["scopes"]
