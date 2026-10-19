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


class TestClickUpClientInitialization:
    def test_default_base_url(self):
        settings = _make_settings()
        client = ClickUpClient(settings)
        assert client._base_url == "https://api.clickup.com/api/v2"

    def test_base_url_trailing_slash_removed(self):
        settings = _make_settings(CLICKUP_API_BASE="https://api.clickup.com/api/v2/")
        client = ClickUpClient(settings)
        assert client._base_url == "https://api.clickup.com/api/v2"

    def test_default_access_token_empty(self):
        settings = _make_settings()
        client = ClickUpClient(settings)
        assert client._access_token == ""


class TestClickUpClientRequestError:
    async def test_404_error(self):
        settings = _make_settings()
        client = ClickUpClient(settings)
        client._access_token = "test-token"

        with patch("clickup_mcp.clickup_client.httpx.AsyncClient") as mock_httpx:
            mock_response = MagicMock()
            mock_response.status_code = 404
            mock_response.json.return_value = {"message": "Not found", "code": "NOT_FOUND"}
            mock_response.text = '{"message": "Not found"}'
            mock_httpx_instance = MagicMock()
            mock_httpx_instance.request = AsyncMock(return_value=mock_response)
            mock_httpx.return_value.__aenter__ = AsyncMock(return_value=mock_httpx_instance)
            mock_httpx.return_value.__aexit__ = AsyncMock(return_value=None)

            with pytest.raises(ClickUpAPIError) as exc_info:
                await client._request(
                    "GET",
                    "/workspace/ws-invalid",
                    client._build_headers(),
                )
            assert exc_info.value.status_code == 404
            assert exc_info.value.message == "Not found"
            assert exc_info.value.code == "NOT_FOUND"

    async def test_500_error_no_json(self):
        settings = _make_settings()
        client = ClickUpClient(settings)
        client._access_token = "test-token"

        with patch("clickup_mcp.clickup_client.httpx.AsyncClient") as mock_httpx:
            mock_response = MagicMock()
            mock_response.status_code = 500
            mock_response.json.side_effect = Exception("Not JSON")
            mock_response.text = "Internal Server Error"
            mock_httpx_instance = MagicMock()
            mock_httpx_instance.request = AsyncMock(return_value=mock_response)
            mock_httpx.return_value.__aenter__ = AsyncMock(return_value=mock_httpx_instance)
            mock_httpx.return_value.__aexit__ = AsyncMock(return_value=None)

            with pytest.raises(ClickUpAPIError) as exc_info:
                await client._request(
                    "GET",
                    "/workspace/ws-1",
                    client._build_headers(),
                )
            assert exc_info.value.status_code == 500
            assert exc_info.value.message == "Internal Server Error"

    async def test_204_no_content(self):
        settings = _make_settings()
        client = ClickUpClient(settings)
        client._access_token = "test-token"

        with patch("clickup_mcp.clickup_client.httpx.AsyncClient") as mock_httpx:
            mock_response = MagicMock()
            mock_response.status_code = 204
            mock_response.text = ""
            mock_httpx_instance = MagicMock()
            mock_httpx_instance.request = AsyncMock(return_value=mock_response)
            mock_httpx.return_value.__aenter__ = AsyncMock(return_value=mock_httpx_instance)
            mock_httpx.return_value.__aexit__ = AsyncMock(return_value=None)

            result = await client._request(
                "DELETE",
                "/task/task-1",
                client._build_headers(),
            )
            assert result == {}

    async def test_201_with_json(self):
        settings = _make_settings()
        client = ClickUpClient(settings)
        client._access_token = "test-token"

        with patch("clickup_mcp.clickup_client.httpx.AsyncClient") as mock_httpx:
            mock_response = MagicMock()
            mock_response.status_code = 201
            mock_response.json.return_value = {"id": "new-task", "name": "New"}
            mock_response.text = '{"id": "new-task"}'
            mock_httpx_instance = MagicMock()
            mock_httpx_instance.request = AsyncMock(return_value=mock_response)
            mock_httpx.return_value.__aenter__ = AsyncMock(return_value=mock_httpx_instance)
            mock_httpx.return_value.__aexit__ = AsyncMock(return_value=None)

            result = await client._request(
                "POST",
                "/list/list-1/task",
                client._build_headers(),
                json_body={"name": "New"},
            )
            assert result["id"] == "new-task"


class TestClickUpClientBuildHeaders:
    def test_headers_format(self):
        settings = _make_settings()
        client = ClickUpClient(settings)
        client._access_token = "Bearer abc123"
        headers = client._build_headers()
        assert headers["Authorization"] == "Bearer abc123"
        assert headers["Content-Type"] == "application/json"
        assert headers["User-Agent"] == "ClickUpMCP/1.0"

    def test_headers_empty_token(self):
        settings = _make_settings()
        client = ClickUpClient(settings)
        headers = client._build_headers()
        assert "Authorization" not in headers


class TestClickUpClientMethodSignatures:
    def test_get_workspace_signature(self):
        settings = _make_settings()
        client = ClickUpClient(settings)
        assert hasattr(client, "get_workspace")

    def test_get_space_tasks_signature(self):
        settings = _make_settings()
        client = ClickUpClient(settings)
        assert hasattr(client, "get_space_tasks")

    def test_get_list_tasks_signature(self):
        settings = _make_settings()
        client = ClickUpClient(settings)
        assert hasattr(client, "get_list_tasks")

    def test_create_task_signature(self):
        settings = _make_settings()
        client = ClickUpClient(settings)
        assert hasattr(client, "create_task")

    def test_get_task_signature(self):
        settings = _make_settings()
        client = ClickUpClient(settings)
        assert hasattr(client, "get_task")

    def test_get_task_statuses_signature(self):
        settings = _make_settings()
        client = ClickUpClient(settings)
        assert hasattr(client, "get_task_statuses")

    def test_get_team_lists_signature(self):
        settings = _make_settings()
        client = ClickUpClient(settings)
        assert hasattr(client, "get_team_lists")

    def test_get_folder_lists_signature(self):
        settings = _make_settings()
        client = ClickUpClient(settings)
        assert hasattr(client, "get_folder_lists")

    def test_get_space_lists_signature(self):
        settings = _make_settings()
        client = ClickUpClient(settings)
        assert hasattr(client, "get_space_lists")

    def test_get_workspace_teams_signature(self):
        settings = _make_settings()
        client = ClickUpClient(settings)
        assert hasattr(client, "get_workspace_teams")
