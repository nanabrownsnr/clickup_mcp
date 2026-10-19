from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from mcp.types import TextContent, CallToolResult

from clickup_mcp.config import Settings
from clickup_mcp.clickup_client import ClickUpClient, ClickUpAPIError
from clickup_mcp.tools.base import MCPToolContext, list_tasks_tool, create_task_tool
from clickup_mcp.storage import TokenStore
from clickup_mcp.crypto import encrypt_token


def _make_settings(**overrides) -> Settings:
    base = {
        "CLICKUP_API_TOKEN": "test-api-token",
        "ENCRYPTION_KEY": "l2G_gvqENw5Xdptya18vB8IyK7yEbZiLI4PtCP-6lGE",
        "MONGODB_URI": "mongodb://localhost:27017",
    }
    base.update(overrides)
    return Settings(**base)


def _make_mock_token() -> dict:
    """Generate a properly encrypted mock token."""
    token_data = encrypt_token(
        "mock-api-token-for-testing",
        "l2G_gvqENw5Xdptya18vB8IyK7yEbZiLI4PtCP-6lGE",
        "test-persona",
    )
    return {"encrypted_token": token_data}


def _make_context(**overrides) -> MCPToolContext:
    settings = _make_settings(**overrides)
    mock_store = MagicMock(spec=TokenStore)
    mock_store.get_token = AsyncMock(return_value=None)
    mock_store.get_all_tokens = AsyncMock(return_value=[])
    return MCPToolContext(settings, mock_store)


class TestListTasksTool:
    async def test_list_tasks_with_list_id(self):
        ctx = _make_context()
        mock_token = _make_mock_token()
        ctx.store.get_token = AsyncMock(return_value=mock_token)
        ctx.store.get_all_tokens = AsyncMock(return_value=[{"workspace_id": "ws-123"}])
        ctx._current_persona_id = "test-persona"

        mock_tasks_response = {
            "tasks": [
                {
                    "id": "task-1",
                    "name": "Test Task 1",
                    "status": {"status_name": "In Progress"},
                    "priority": 2,
                    "assignee": "user-1",
                    "due_date": "2025-12-31",
                    "description": "A test task",
                }
            ]
        }

        mock_client = MagicMock(spec=ClickUpClient)
        mock_client.get_list_tasks = AsyncMock(return_value=mock_tasks_response)
        mock_client.settings = ctx.settings
        ctx.get_client = MagicMock(return_value=mock_client)

        result = await list_tasks_tool(
            ctx,
            list_id="list-abc",
            workspace_id="ws-123",
        )

        assert isinstance(result, CallToolResult)
        assert len(result.content) == 1
        assert isinstance(result.content[0], TextContent)
        assert "Found 1 task(s)" in result.content[0].text
        assert "Test Task 1" in result.content[0].text
        assert result.structuredContent["count"] == 1
        assert result.structuredContent["tasks"][0]["id"] == "task-1"

    async def test_list_tasks_with_space_id(self):
        ctx = _make_context()
        mock_token = _make_mock_token()
        ctx.store.get_token = AsyncMock(return_value=mock_token)
        ctx._current_persona_id = "test-persona"

        mock_space_response = {"tasks": []}

        mock_client = MagicMock(spec=ClickUpClient)
        mock_client.get_space_tasks = AsyncMock(return_value=mock_space_response)
        mock_client.settings = ctx.settings
        ctx.get_client = MagicMock(return_value=mock_client)

        result = await list_tasks_tool(
            ctx,
            space_id="space-xyz",
            workspace_id="ws-123",
        )

        assert isinstance(result, CallToolResult)
        assert result.structuredContent["count"] == 0
        mock_client.get_space_tasks.assert_called_once()

    async def test_list_tasks_no_workspace_fails(self):
        ctx = _make_context()
        ctx.store.get_all_tokens = AsyncMock(return_value=[])
        ctx._current_persona_id = "test-persona"

        with pytest.raises(ValueError, match="No workspace selected"):
            await list_tasks_tool(ctx)

    async def test_list_tasks_no_token_raises(self):
        ctx = _make_context()
        ctx.store.get_token = AsyncMock(return_value=None)
        ctx.store.get_all_tokens = AsyncMock(return_value=[{"workspace_id": "ws-1"}])
        ctx._current_persona_id = "test-persona"

        with pytest.raises(ValueError, match="No API token found"):
            await list_tasks_tool(ctx, list_id="list-abc", workspace_id="ws-1")

    async def test_list_tasks_no_list_or_space_id(self):
        ctx = _make_context()
        mock_token = _make_mock_token()
        ctx.store.get_token = AsyncMock(return_value=mock_token)
        ctx._current_persona_id = "test-persona"

        with pytest.raises(ValueError, match="Either list_id or space_id"):
            await list_tasks_tool(ctx, workspace_id="ws-1")

    async def test_list_tasks_decrypt_failure(self):
        ctx = _make_context()
        ctx.store.get_token = AsyncMock(return_value={"encrypted_token": {"bad": "data"}})
        ctx._current_persona_id = "test-persona"

        with pytest.raises(ValueError, match="Failed to decrypt"):
            await list_tasks_tool(ctx, list_id="list-abc", workspace_id="ws-1")


class TestCreateTaskTool:
    async def test_create_task_success(self):
        ctx = _make_context()
        mock_token = _make_mock_token()
        ctx.store.get_token = AsyncMock(return_value=mock_token)
        ctx._current_persona_id = "test-persona"

        mock_task_response = {
            "id": "new-task-1",
            "name": "New Task",
            "status": {"status_name": "Not Started"},
            "priority": 3,
        }

        mock_client = MagicMock(spec=ClickUpClient)
        mock_client.create_task = AsyncMock(return_value=mock_task_response)
        mock_client.settings = ctx.settings
        ctx.get_client = MagicMock(return_value=mock_client)

        result = await create_task_tool(
            ctx,
            list_id="list-abc",
            name="New Task",
            description="A new task description",
            workspace_id="ws-123",
        )

        assert isinstance(result, CallToolResult)
        assert len(result.content) == 1
        assert isinstance(result.content[0], TextContent)
        assert "Task created successfully" in result.content[0].text
        assert result.structuredContent["success"] is True
        assert result.structuredContent["task"]["id"] == "new-task-1"
        mock_client.create_task.assert_called_once_with(
            list_id="list-abc",
            name="New Task",
            description="A new task description",
            priority=None,
            status=None,
            assignee=None,
            due_date=None,
        )

    async def test_create_task_minimal(self):
        ctx = _make_context()
        mock_token = _make_mock_token()
        ctx.store.get_token = AsyncMock(return_value=mock_token)
        ctx._current_persona_id = "test-persona"

        mock_task_response = {"id": "new-task-2", "name": "Minimal Task", "status": "not_started", "priority": None}

        mock_client = MagicMock(spec=ClickUpClient)
        mock_client.create_task = AsyncMock(return_value=mock_task_response)
        mock_client.settings = ctx.settings
        ctx.get_client = MagicMock(return_value=mock_client)

        result = await create_task_tool(
            ctx,
            list_id="list-abc",
            name="Minimal Task",
            workspace_id="ws-123",
        )

        assert isinstance(result, CallToolResult)
        assert result.structuredContent["success"] is True

    async def test_create_task_no_token(self):
        ctx = _make_context()
        ctx.store.get_token = AsyncMock(return_value=None)
        ctx._current_persona_id = "test-persona"

        with pytest.raises(ValueError, match="No API token found"):
            await create_task_tool(ctx, list_id="list-abc", name="Task", workspace_id="ws-1")

    async def test_create_task_api_error(self):
        ctx = _make_context()
        mock_token = _make_mock_token()
        ctx.store.get_token = AsyncMock(return_value=mock_token)
        ctx._current_persona_id = "test-persona"

        mock_client = MagicMock(spec=ClickUpClient)
        mock_client.create_task = AsyncMock(side_effect=ClickUpAPIError(400, "List not found", "LIST_NOT_FOUND"))
        mock_client.settings = ctx.settings
        ctx.get_client = MagicMock(return_value=mock_client)

        with pytest.raises(ClickUpAPIError) as exc_info:
            await create_task_tool(
                ctx,
                list_id="list-invalid",
                name="Task",
                workspace_id="ws-123",
            )
        assert exc_info.value.status_code == 400
        assert exc_info.value.message == "List not found"
        assert exc_info.value.code == "LIST_NOT_FOUND"

    async def test_create_task_with_all_fields(self):
        ctx = _make_context()
        mock_token = _make_mock_token()
        ctx.store.get_token = AsyncMock(return_value=mock_token)
        ctx._current_persona_id = "test-persona"

        mock_task_response = {
            "id": "full-task-1",
            "name": "Full Task",
            "status": {"status_name": "In Progress"},
            "priority": 1,
            "assignee": "user-1",
            "due_date": "2025-12-31",
        }

        mock_client = MagicMock(spec=ClickUpClient)
        mock_client.create_task = AsyncMock(return_value=mock_task_response)
        mock_client.settings = ctx.settings
        ctx.get_client = MagicMock(return_value=mock_client)

        result = await create_task_tool(
            ctx,
            list_id="list-abc",
            name="Full Task",
            description="Full description",
            priority="1",
            status="in_progress",
            assignee="user-1",
            due_date="2025-12-31T00:00:00.000Z",
            workspace_id="ws-123",
        )

        assert isinstance(result, CallToolResult)
        assert result.structuredContent["success"] is True
        assert result.structuredContent["task"]["id"] == "full-task-1"
        mock_client.create_task.assert_called_once_with(
            list_id="list-abc",
            name="Full Task",
            description="Full description",
            priority="1",
            status="in_progress",
            assignee="user-1",
            due_date="2025-12-31T00:00:00.000Z",
        )


class TestToolRegistration:
    async def test_register_mcp_tools(self):
        from mcp.server.fastmcp import FastMCP

        settings = _make_settings()
        mock_store = MagicMock(spec=TokenStore)
        ctx = MCPToolContext(settings, mock_store)

        mcp = FastMCP("test")
        from clickup_mcp.tools.base import register_mcp_tools
        register_mcp_tools(mcp, ctx)

        tools = await mcp.list_tools()
        assert tools is not None


class TestClickUpAPIError:
    def test_api_error_message(self):
        err = ClickUpAPIError(404, "Not found", "NOT_FOUND")
        assert err.status_code == 404
        assert err.message == "Not found"
        assert err.code == "NOT_FOUND"

    def test_api_error_no_code(self):
        err = ClickUpAPIError(500, "Internal error")
        assert err.status_code == 500
        assert err.message == "Internal error"
        assert err.code is None


class TestToolInputOutputFormat:
    async def test_list_tasks_structured_content_format(self):
        ctx = _make_context()
        mock_token = _make_mock_token()
        ctx.store.get_token = AsyncMock(return_value=mock_token)
        ctx.store.get_all_tokens = AsyncMock(return_value=[{"workspace_id": "ws-123"}])
        ctx._current_persona_id = "test-persona"

        mock_tasks_response = {
            "tasks": [
                {
                    "id": "task-1",
                    "name": "Task One",
                    "status": {"status_name": "Done"},
                    "priority": 3,
                    "assignee": "user-1",
                    "due_date": "2025-06-01",
                    "description": "Description text",
                }
            ]
        }

        mock_client = MagicMock(spec=ClickUpClient)
        mock_client.get_list_tasks = AsyncMock(return_value=mock_tasks_response)
        mock_client.settings = ctx.settings
        ctx.get_client = MagicMock(return_value=mock_client)

        result = await list_tasks_tool(
            ctx,
            list_id="list-abc",
            workspace_id="ws-123",
        )

        sc = result.structuredContent
        assert isinstance(sc, dict)
        assert "workspace_id" in sc
        assert sc["workspace_id"] == "ws-123"
        assert "filter" in sc
        assert "count" in sc
        assert sc["count"] == 1
        assert "tasks" in sc
        assert isinstance(sc["tasks"], list)
        assert "page_size" in sc

    async def test_list_tasks_empty_tasks(self):
        ctx = _make_context()
        mock_token = _make_mock_token()
        ctx.store.get_token = AsyncMock(return_value=mock_token)
        ctx.store.get_all_tokens = AsyncMock(return_value=[{"workspace_id": "ws-1"}])
        ctx._current_persona_id = "test-persona"

        mock_client = MagicMock(spec=ClickUpClient)
        mock_client.get_list_tasks = AsyncMock(return_value={"tasks": []})
        mock_client.settings = ctx.settings
        ctx.get_client = MagicMock(return_value=mock_client)

        result = await list_tasks_tool(
            ctx,
            list_id="list-abc",
            workspace_id="ws-1",
        )

        assert result.structuredContent["count"] == 0
        assert "Found 0 task(s)" in result.content[0].text

    async def test_create_task_structured_content_format(self):
        ctx = _make_context()
        mock_token = _make_mock_token()
        ctx.store.get_token = AsyncMock(return_value=mock_token)
        ctx._current_persona_id = "test-persona"

        mock_task_response = {
            "id": "task-new",
            "name": "Created Task",
            "status": {"status_name": "Not Started"},
            "priority": 2,
        }

        mock_client = MagicMock(spec=ClickUpClient)
        mock_client.create_task = AsyncMock(return_value=mock_task_response)
        mock_client.settings = ctx.settings
        ctx.get_client = MagicMock(return_value=mock_client)

        result = await create_task_tool(
            ctx,
            list_id="list-xyz",
            name="Created Task",
            workspace_id="ws-1",
        )

        sc = result.structuredContent
        assert sc["success"] is True
        assert "task" in sc
        assert sc["task"]["id"] == "task-new"
        assert sc["list_id"] == "list-xyz"
        assert sc["workspace_id"] == "ws-1"

    async def test_list_tasks_with_all_filters(self):
        ctx = _make_context()
        mock_token = _make_mock_token()
        ctx.store.get_token = AsyncMock(return_value=mock_token)
        ctx.store.get_all_tokens = AsyncMock(return_value=[{"workspace_id": "ws-1"}])
        ctx._current_persona_id = "test-persona"

        mock_client = MagicMock(spec=ClickUpClient)
        mock_client.get_list_tasks = AsyncMock(return_value={"tasks": []})
        mock_client.settings = ctx.settings
        ctx.get_client = MagicMock(return_value=mock_client)

        await list_tasks_tool(
            ctx,
            list_id="list-abc",
            workspace_id="ws-1",
            status="done",
            assignee="user-42",
            priority="1",
            page_size=50,
            include_archived=True,
        )

        mock_client.get_list_tasks.assert_called_once_with(
            list_id="list-abc",
            status="done",
            assignee="user-42",
            priority="1",
            page_size=50,
            include_archived=True,
        )

    async def test_create_task_minimal_fields(self):
        ctx = _make_context()
        mock_token = _make_mock_token()
        ctx.store.get_token = AsyncMock(return_value=mock_token)
        ctx._current_persona_id = "test-persona"

        mock_task_response = {"id": "min-task", "name": "Minimal", "status": "not_started"}

        mock_client = MagicMock(spec=ClickUpClient)
        mock_client.create_task = AsyncMock(return_value=mock_task_response)
        mock_client.settings = ctx.settings
        ctx.get_client = MagicMock(return_value=mock_client)

        await create_task_tool(
            ctx,
            list_id="list-abc",
            name="Minimal",
            workspace_id="ws-1",
        )

        mock_client.create_task.assert_called_once_with(
            list_id="list-abc",
            name="Minimal",
            description="",
            priority=None,
            status=None,
            assignee=None,
            due_date=None,
        )

    async def test_list_tasks_auto_workspace_resolution(self):
        """When workspace_id is not provided, first connected workspace is used."""
        ctx = _make_context()
        mock_token = _make_mock_token()
        ctx.store.get_token = AsyncMock(return_value=mock_token)
        ctx.store.get_all_tokens = AsyncMock(return_value=[
            {"workspace_id": "auto-ws-1"},
            {"workspace_id": "auto-ws-2"},
        ])
        ctx._current_persona_id = "test-persona"

        mock_client = MagicMock(spec=ClickUpClient)
        mock_client.get_list_tasks = AsyncMock(return_value={"tasks": []})
        mock_client.settings = ctx.settings
        ctx.get_client = MagicMock(return_value=mock_client)

        await list_tasks_tool(ctx, list_id="list-abc")

        mock_client.get_list_tasks.assert_called_once()
        assert mock_client.get_list_tasks.call_args[1]["list_id"] == "list-abc"


class TestTokenValidationClient:
    def test_client_has_validate_token(self):
        settings = _make_settings()
        client = ClickUpClient(settings)
        assert hasattr(client, "validate_token")
        assert callable(client.validate_token)

    async def test_validate_token_calls_api(self):
        settings = _make_settings()
        client = ClickUpClient(settings)
        client._access_token = "test-token"

        with patch("clickup_mcp.clickup_client.httpx.AsyncClient") as mock_httpx:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {"id": "team-123", "name": "Test"}
            mock_response.text = ""
            mock_httpx_instance = MagicMock()
            mock_httpx_instance.request = AsyncMock(return_value=mock_response)
            mock_httpx.return_value.__aenter__ = AsyncMock(return_value=mock_httpx_instance)
            mock_httpx.return_value.__aexit__ = AsyncMock(return_value=None)

            result = await client.validate_token("test-token")
            assert result["id"] == "team-123"
            assert result["name"] == "Test"

    async def test_validate_token_unauthorized(self):
        settings = _make_settings()
        client = ClickUpClient(settings)
        client._access_token = "invalid-token"

        with patch("clickup_mcp.clickup_client.httpx.AsyncClient") as mock_httpx:
            mock_response = MagicMock()
            mock_response.status_code = 401
            mock_response.json.return_value = {"message": "Unauthorized"}
            mock_httpx_instance = MagicMock()
            mock_httpx_instance.request = AsyncMock(return_value=mock_response)
            mock_httpx.return_value.__aenter__ = AsyncMock(return_value=mock_httpx_instance)
            mock_httpx.return_value.__aexit__ = AsyncMock(return_value=None)

            with pytest.raises(ClickUpAPIError) as exc_info:
                await client.validate_token("invalid-token")
            assert exc_info.value.status_code == 401
            assert exc_info.value.message == "Unauthorized"
