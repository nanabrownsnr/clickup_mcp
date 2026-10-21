"""ClickUp MCP tools: list_tasks, create_task.

Uses @mcp.tool() returning ToolResult (fastmcp 4.x).
"""

from __future__ import annotations

from typing import Any, Optional

from fastmcp.tools import ToolResult

from clickup_mcp.clickup_client import ClickUpClient, ClickUpAPIError
from clickup_mcp.config import Settings
from clickup_mcp.crypto import decrypt_token
from clickup_mcp.storage import TokenStore, get_active_store

NL = chr(10)


def register_mcp_tools(mcp, settings: Settings):
    @mcp.tool()
    async def list_tasks(
        list_id: Optional[str] = None,
        space_id: Optional[str] = None,
        workspace_id: Optional[str] = None,
        status: Optional[str] = None,
        assignee: Optional[str] = None,
        priority: Optional[str] = None,
        page_size: int = 25,
        include_archived: bool = False,
    ) -> ToolResult:
        """List tasks in a ClickUp space or list with optional filters."""
        store = get_active_store()
        if store is None:
            raise ValueError("Token storage is not available")

        persona_id = _get_current_persona_id()
        resolved_workspace = await _resolve_workspace(store, persona_id, workspace_id)
        client = await _get_authenticated_client(store, settings, resolved_workspace, persona_id)

        task_filter_parts = ["workspace=" + resolved_workspace]
        if list_id:
            task_filter_parts.append("list=" + list_id)
        elif space_id:
            task_filter_parts.append("space=" + space_id)
        task_filter = ", ".join(task_filter_parts)

        if list_id:
            result = await client.get_list_tasks(
                list_id=list_id, status=status, assignee=assignee,
                priority=priority, page_size=page_size,
                include_archived=include_archived,
            )
        elif space_id:
            result = await client.get_space_tasks(
                space_id=space_id, status=status, assignee=assignee,
                priority=priority, page_size=page_size,
            )
        else:
            raise ValueError("Either list_id or space_id must be provided")

        tasks = result.get("tasks", [])
        readable_parts = ["Found " + str(len(tasks)) + " task(s) for " + task_filter + ":"]
        for task in tasks:
            readable_parts.append(_format_task(task))

        return ToolResult(
            content=NL.join(readable_parts),
            structured_content={
                "workspace_id": resolved_workspace,
                "filter": task_filter,
                "count": len(tasks),
                "tasks": tasks,
                "page_size": page_size,
            },
        )


    @mcp.tool()
    async def create_task(
        list_id: str,
        name: str,
        description: Optional[str] = None,
        priority: Optional[str] = None,
        status: Optional[str] = None,
        assignee: Optional[str] = None,
        due_date: Optional[str] = None,
        workspace_id: Optional[str] = None,
    ) -> ToolResult:
        """Create a new task in a specified ClickUp list."""
        store = get_active_store()
        if store is None:
            raise ValueError("Token storage is not available")

        persona_id = _get_current_persona_id()
        resolved_workspace = await _resolve_workspace(store, persona_id, workspace_id)
        client = await _get_authenticated_client(store, settings, resolved_workspace, persona_id)

        result = await client.create_task(
            list_id=list_id, name=name, description=description or "",
            priority=priority, status=status, assignee=assignee, due_date=due_date,
        )

        _lines = [
            "Task created successfully!",
            "  ID: " + str(result.get("id", "N/A")),
            "  Name: " + str(result.get("name", "N/A")),
            "  List: " + list_id,
            "  Workspace: " + resolved_workspace,
        ]
        readable = NL.join(_lines)

        return ToolResult(
            content=readable,
            structured_content={
                "success": True,
                "task": result,
                "list_id": list_id,
                "workspace_id": resolved_workspace,
            },
        )


_current_persona_id_var: str = "anonymous"


def _get_current_persona_id() -> str:
    return _current_persona_id_var


def _set_current_persona_id(persona_id: str):
    global _current_persona_id_var
    _current_persona_id_var = persona_id


async def _get_authenticated_client(store, settings, workspace_id, persona_id):
    """Get ClickUp client from stored token (OAuth2 or PAT)."""
    oauth_token_doc = await store.get_oauth_token(persona_id, workspace_id)
    if oauth_token_doc:
        try:
            access_token = decrypt_token(
                oauth_token_doc["encrypted_access_token"],
                settings.ENCRYPTION_KEY,
                persona_id + ":" + workspace_id,
            )
            client = ClickUpClient(settings)
            client._access_token = access_token
            return client
        except Exception:
            pass

    token_doc = await store.get_token(persona_id, workspace_id)
    if not token_doc:
        raise ValueError(
            "No API token found for persona=" + persona_id + ", workspace=" + workspace_id
            + ". Please connect a workspace first."
        )
    access_token = decrypt_token(
        token_doc["encrypted_token"], settings.ENCRYPTION_KEY, persona_id,
    )
    client = ClickUpClient(settings)
    client._access_token = access_token
    return client


async def _resolve_workspace(store, persona_id, workspace_id):
    if not workspace_id:
        tokens = await store.get_all_tokens(persona_id)
        if not tokens:
            raise ValueError(
                "No workspace selected and no connected workspaces found."
            )
        workspace_id = tokens[0]["workspace_id"]
    return workspace_id


def _format_task(task: dict) -> str:
    status = task.get("status", {})
    if isinstance(status, dict):
        status_text = status.get("status_name", "Unknown")
    else:
        status_text = str(status or "Unknown")
    assignee = task.get("assignee")
    assignee_text = ("@" + str(assignee)) if assignee else "Unassigned"
    priority = task.get("priority")
    priority_map = {1: "urgent", 2: "high", 3: "normal", 4: "low"}
    priority_text = priority_map.get(priority, "none") if priority else "none"
    due_date = task.get("due_date")
    due_text = ("Due: " + str(due_date)) if due_date else "No due date"
    parts = [
        "Task: " + str(task.get("name", "Untitled")),
        "  ID: " + str(task.get("id", "N/A")),
        "  Status: " + status_text,
        "  Priority: " + priority_text,
        "  Assignee: " + assignee_text,
        "  " + due_text,
        "  Description: " + str(task.get("description", "No description"))[:200],
    ]
    return NL.join(parts)
