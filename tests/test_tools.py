"""Tests for ClickUp MCP tools using FastMCP 4.x pattern."""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from fastmcp import FastMCP
from clickup_mcp.config import Settings
from clickup_mcp.clickup_client import ClickUpClient, ClickUpAPIError
from clickup_mcp.crypto import encrypt_token
from clickup_mcp.storage import TokenStore
from clickup_mcp.tools.base import register_mcp_tools


def _make_settings(**overrides):
    base = {
        "CLICKUP_API_TOKEN": "test-api-token",
        "ENCRYPTION_KEY": "l2G_gvqENw5Xdptya18vB8IyK7yEbZiLI4PtCP-6lGE",
        "MONGODB_URI": "mongodb://localhost:27017",
    }
    base.update(overrides)
    return Settings(**base)


def _make_mock_token():
    return encrypt_token(
        "mock-api-token-for-testing",
        "l2G_gvqENw5Xdptya18vB8IyK7yEbZiLI4PtCP-6lGE",
        "test-persona",
    )


def _make_mcp(settings):
    mcp = FastMCP("test")
    register_mcp_tools(mcp, settings)
    return mcp


class TestListTasksTool:
    async def test_list_tasks_with_list_id(self):
        settings = _make_settings()
        mcp = _make_mcp(settings)
        mock_store = MagicMock(spec=TokenStore)
        mock_store.get_token = AsyncMock(return_value={"encrypted_token": _make_mock_token()})
        mock_store.get_all_tokens = AsyncMock(return_value=[{"workspace_id": "ws-123"}])
        mock_store.get_oauth_token = AsyncMock(return_value=None)

        mock_client = MagicMock(spec=ClickUpClient)
        mock_client.get_list_tasks = AsyncMock(return_value={
            "tasks": [{
                "id": "task-1", "name": "Test Task 1",
                "status": {"status_name": "In Progress"},
                "priority": 2, "assignee": "user-1",
                "due_date": "2025-12-31", "description": "A test task",
            }]
        })

        with patch("clickup_mcp.tools.base.get_active_store", return_value=mock_store):
            with patch("clickup_mcp.tools.base.ClickUpClient", return_value=mock_client):
                result = await mcp.call_tool("list_tasks", {"list_id": "list-abc", "workspace_id": "ws-123"})
                assert result is not None
                assert result.structured_content["count"] == 1
                assert result.structured_content["tasks"][0]["id"] == "task-1"

    async def test_list_tasks_no_workspace_fails(self):
        settings = _make_settings()
        mcp = _make_mcp(settings)
        mock_store = MagicMock(spec=TokenStore)
        mock_store.get_all_tokens = AsyncMock(return_value=[])
        mock_store.get_oauth_token = AsyncMock(return_value=None)

        with patch("clickup_mcp.tools.base.get_active_store", return_value=mock_store):
            with pytest.raises(Exception):
                await mcp.call_tool("list_tasks", {"workspace_id": "ws-123", "list_id": "x"})


class TestCreateTaskTool:
    async def test_create_task_success(self):
        settings = _make_settings()
        mcp = _make_mcp(settings)
        mock_store = MagicMock(spec=TokenStore)
        mock_store.get_token = AsyncMock(return_value={"encrypted_token": _make_mock_token()})
        mock_store.get_all_tokens = AsyncMock(return_value=[{"workspace_id": "ws-123"}])
        mock_store.get_oauth_token = AsyncMock(return_value=None)

        mock_client = MagicMock(spec=ClickUpClient)
        mock_client.create_task = AsyncMock(return_value={
            "id": "new-task-1", "name": "New Task",
            "status": {"status_name": "Not Started"}, "priority": 3,
        })

        with patch("clickup_mcp.tools.base.get_active_store", return_value=mock_store):
            with patch("clickup_mcp.tools.base.ClickUpClient", return_value=mock_client):
                result = await mcp.call_tool("create_task", {
                    "list_id": "list-abc", "name": "New Task", "workspace_id": "ws-123",
                })
                assert result is not None
                assert result.structured_content["success"] is True
                assert result.structured_content["task"]["id"] == "new-task-1"

    async def test_create_task_no_token(self):
        settings = _make_settings()
        mcp = _make_mcp(settings)
        mock_store = MagicMock(spec=TokenStore)
        mock_store.get_token = AsyncMock(return_value=None)
        mock_store.get_all_tokens = AsyncMock(return_value=[{"workspace_id": "ws-1"}])
        mock_store.get_oauth_token = AsyncMock(return_value=None)

        with patch("clickup_mcp.tools.base.get_active_store", return_value=mock_store):
            with pytest.raises(Exception):
                await mcp.call_tool("create_task", {
                    "list_id": "list-abc", "name": "Task", "workspace_id": "ws-1",
                })


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
