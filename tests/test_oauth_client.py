from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from clickup_mcp.config import Settings
from clickup_mcp.clickup_client import ClickUpClient, ClickUpAPIError


def _make_settings(**overrides) -> Settings:
    base = {
        "CLICKUP_API_TOKEN": "test-api-token",
        "ENCRYPTION_KEY": "l2G_gvqENw5Xdptya18vB8IyK7yEbZiLI4PtCP-6lGE",
        "MONGODB_URI": "mongodb://localhost:27017",
    }
    base.update(overrides)
    return Settings(**base)


class TestOAuth2ClientMethods:
    def test_has_authorization_url_method(self):
        settings = _make_settings()
        client = ClickUpClient(settings)
        assert hasattr(client, "get_oauth_authorization_url")
        assert callable(client.get_oauth_authorization_url)

    def test_has_exchange_code_method(self):
        settings = _make_settings()
        client = ClickUpClient(settings)
        assert hasattr(client, "exchange_code_for_token")
        assert callable(client.exchange_code_for_token)

    def test_has_refresh_token_method(self):
        settings = _make_settings()
        client = ClickUpClient(settings)
        assert hasattr(client, "refresh_access_token")
        assert callable(client.refresh_access_token)

    def test_has_revoke_token_method(self):
        settings = _make_settings()
        client = ClickUpClient(settings)
        assert hasattr(client, "revoke_token")
        assert callable(client.revoke_token)

    async def test_authorization_url_generation(self):
        settings = _make_settings()
        client = ClickUpClient(settings)
        url = await client.get_oauth_authorization_url(
            state="test-state-123",
            redirect_uri="http://localhost/callback",
            client_id="my-client-id",
        )
        assert "https://app.clickup.com/oauth/authorize" in url
        assert "state=test-state-123" in url
        assert "client_id=my-client-id" in url
        assert "redirect_uri=http%3A%2F%2Flocalhost%2Fcallback" in url

    async def test_authorization_url_custom_auth_base(self):
        settings = _make_settings()
        client = ClickUpClient(settings)
        url = await client.get_oauth_authorization_url(
            state="test-state",
            redirect_uri="http://localhost/callback",
            client_id="client",
            auth_base_url="https://custom.clickup.com",
        )
        assert "https://custom.clickup.com/oauth/authorize" in url

    async def test_exchange_code_for_token_success(self):
        settings = _make_settings()
        client = ClickUpClient(settings)

        with patch("clickup_mcp.clickup_client.httpx.AsyncClient") as mock_httpx:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {
                "access_token": "new-access-token",
                "refresh_token": "new-refresh-token",
                "expires_in": 3600,
                "token_type": "Bearer",
            }
            mock_response.text = ""
            mock_httpx_instance = MagicMock()
            mock_httpx_instance.post = AsyncMock(return_value=mock_response)
            mock_httpx.return_value.__aenter__ = AsyncMock(return_value=mock_httpx_instance)
            mock_httpx.return_value.__aexit__ = AsyncMock(return_value=None)

            result = await client.exchange_code_for_token(
                code="auth-code-123",
                redirect_uri="http://localhost/callback",
                client_id="client-id",
                client_secret="client-secret",
            )

            assert result["access_token"] == "new-access-token"
            assert result["refresh_token"] == "new-refresh-token"
            assert result["expires_in"] == 3600

    async def test_exchange_code_for_token_failure(self):
        settings = _make_settings()
        client = ClickUpClient(settings)

        with patch("clickup_mcp.clickup_client.httpx.AsyncClient") as mock_httpx:
            mock_response = MagicMock()
            mock_response.status_code = 400
            mock_response.json.return_value = {
                "message": "Invalid grant type",
                "code": "INVALID_GRANT",
            }
            mock_response.text = '{"message": "Invalid grant type"}'
            mock_httpx_instance = MagicMock()
            mock_httpx_instance.post = AsyncMock(return_value=mock_response)
            mock_httpx.return_value.__aenter__ = AsyncMock(return_value=mock_httpx_instance)
            mock_httpx.return_value.__aexit__ = AsyncMock(return_value=None)

            with pytest.raises(ClickUpAPIError) as exc_info:
                await client.exchange_code_for_token(
                    code="bad-code",
                    redirect_uri="http://localhost/callback",
                    client_id="client-id",
                    client_secret="client-secret",
                )
            assert exc_info.value.status_code == 400
            assert exc_info.value.message == "Invalid grant type"
            assert exc_info.value.code == "INVALID_GRANT"

    async def test_refresh_access_token_success(self):
        settings = _make_settings()
        client = ClickUpClient(settings)

        with patch("clickup_mcp.clickup_client.httpx.AsyncClient") as mock_httpx:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {
                "access_token": "refreshed-access-token",
                "refresh_token": "new-refresh-token",
                "expires_in": 7200,
            }
            mock_response.text = ""
            mock_httpx_instance = MagicMock()
            mock_httpx_instance.post = AsyncMock(return_value=mock_response)
            mock_httpx.return_value.__aenter__ = AsyncMock(return_value=mock_httpx_instance)
            mock_httpx.return_value.__aexit__ = AsyncMock(return_value=None)

            result = await client.refresh_access_token(
                refresh_token="old-refresh-token",
                client_id="client-id",
                client_secret="client-secret",
            )

            assert result["access_token"] == "refreshed-access-token"
            assert result["expires_in"] == 7200

    async def test_refresh_access_token_failure(self):
        settings = _make_settings()
        client = ClickUpClient(settings)

        with patch("clickup_mcp.clickup_client.httpx.AsyncClient") as mock_httpx:
            mock_response = MagicMock()
            mock_response.status_code = 401
            mock_response.json.return_value = {
                "message": "Token expired",
                "code": "TOKEN_EXPIRED",
            }
            mock_response.text = '{"message": "Token expired"}'
            mock_httpx_instance = MagicMock()
            mock_httpx_instance.post = AsyncMock(return_value=mock_response)
            mock_httpx.return_value.__aenter__ = AsyncMock(return_value=mock_httpx_instance)
            mock_httpx.return_value.__aexit__ = AsyncMock(return_value=None)

            with pytest.raises(ClickUpAPIError) as exc_info:
                await client.refresh_access_token(
                    refresh_token="expired-token",
                    client_id="client-id",
                    client_secret="client-secret",
                )
            assert exc_info.value.status_code == 401
            assert exc_info.value.code == "TOKEN_EXPIRED"

    async def test_revoke_token_success(self):
        settings = _make_settings()
        client = ClickUpClient(settings)

        with patch("clickup_mcp.clickup_client.httpx.AsyncClient") as mock_httpx:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {}
            mock_response.text = ""
            mock_httpx_instance = MagicMock()
            mock_httpx_instance.post = AsyncMock(return_value=mock_response)
            mock_httpx.return_value.__aenter__ = AsyncMock(return_value=mock_httpx_instance)
            mock_httpx.return_value.__aexit__ = AsyncMock(return_value=None)

            result = await client.revoke_token(
                token="token-to-revoke",
                client_id="client-id",
                client_secret="client-secret",
            )
            assert result == {}

    async def test_revoke_token_failure(self):
        settings = _make_settings()
        client = ClickUpClient(settings)

        with patch("clickup_mcp.clickup_client.httpx.AsyncClient") as mock_httpx:
            mock_response = MagicMock()
            mock_response.status_code = 500
            mock_response.json.return_value = {
                "message": "Server error",
            }
            mock_response.text = '{"message": "Server error"}'
            mock_httpx_instance = MagicMock()
            mock_httpx_instance.post = AsyncMock(return_value=mock_response)
            mock_httpx.return_value.__aenter__ = AsyncMock(return_value=mock_httpx_instance)
            mock_httpx.return_value.__aexit__ = AsyncMock(return_value=None)

            with pytest.raises(ClickUpAPIError) as exc_info:
                await client.revoke_token(
                    token="token",
                    client_id="client-id",
                    client_secret="client-secret",
                )
            assert exc_info.value.status_code == 500
            assert exc_info.value.message == "Server error"
