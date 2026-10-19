from __future__ import annotations

import json
from typing import Any, Optional

from mcp.server.fastmcp import FastMCP
from mcp.types import TextContent, CallToolResult

from clickup_mcp.clickup_client import ClickUpClient, ClickUpAPIError
from clickup_mcp.config import Settings
from clickup_mcp.crypto import decrypt_token
from clickup_mcp.storage import TokenStore


class MCPToolContext:
    def __init__(
        self,
        settings: Settings,
        store: TokenStore,
    ) -> None:
        self.settings = settings
        self.store = store
        self._current_persona_id: str = "anonymous"

    def get_client(self, access_token: str) -> ClickUpClient:
        client = ClickUpClient(self.settings)
        client._access_token = access_token
        return client


async def _get_authenticated_client(
    ctx: MCPToolContext,
    workspace_id: str,
) -> ClickUpClient:
    persona_id = ctx._current_persona_id

    # Try OAuth2 token first
    oauth_token_doc = await ctx.store.get_oauth_token(persona_id, workspace_id)
    if oauth_token_doc:
        try:
            access_token = decrypt_token(
                oauth_token_doc["encrypted_access_token"],
                ctx.settings.ENCRYPTION_KEY,
                f"{persona_id}:{workspace_id}",
            )
            return ctx.get_client(access_token)
        except Exception:
            pass

    # Fall back to PAT
    token_doc = await ctx.store.get_token(persona_id, workspace_id)
    if not token_doc:
        raise ValueError(
            f"No API token found for persona={persona_id}, workspace={workspace_id}. "
            "Please connect a workspace via /project/connect first."
        )
    try:
        access_token = decrypt_token(
            token_doc["encrypted_token"],
            ctx.settings.ENCRYPTION_KEY,
            persona_id,
        )
    except Exception:
        raise ValueError("Failed to decrypt stored API token. Please reconnect.")
    return ctx.get_client(access_token)


async def _resolve_workspace(
    ctx: MCPToolContext,
    workspace_id: Optional[str],
) -> str:
    persona_id = ctx._current_persona_id
    if not workspace_id:
        tokens = await ctx.store.get_all_tokens(persona_id)
        if not tokens:
            raise ValueError(
                "No workspace selected and no connected workspaces found. "
                "Please specify a workspace_id or connect a workspace first."
            )
        workspace_id = tokens[0]["workspace_id"]
    return workspace_id


def _format_task(task: dict[str, Any]) -> str:
    status = task.get("status", {})
    assignee = task.get("assignee")
    priority = task.get("priority")
    due_date = task.get("due_date")

    if isinstance(status, dict):
        status_text = status.get("status_name", "Unknown")
    else:
        status_text = str(status or "Unknown")

    assignee_text = f"@{assignee}" if assignee else "Unassigned"
    priority_map: dict[Any, str] = {None: "none", 1: "urgent", 2: "high", 3: "normal", 4: "low"}
    priority_text = priority_map.get(priority, f"custom:{priority}") if priority else "none"
    due_text = f"Due: {due_date}" if due_date else "No due date"

    return (
        f"Task: {task.get('name', 'Untitled')}\n"
        f"  ID: {task.get('id', 'N/A')}\n"
        f"  Status: {status_text}\n"
        f"  Priority: {priority_text}\n"
        f"  Assignee: {assignee_text}\n"
        f"  {due_text}\n"
        f"  Description: {str(task.get('description', 'No description'))[:200]}\n"
    )


async def list_tasks_tool(
    ctx: MCPToolContext,
    list_id: Optional[str] = None,
    space_id: Optional[str] = None,
    workspace_id: Optional[str] = None,
    status: Optional[str] = None,
    assignee: Optional[str] = None,
    priority: Optional[str] = None,
    page_size: int = 25,
    include_archived: bool = False,
) -> CallToolResult:
    resolved_workspace = await _resolve_workspace(ctx, workspace_id)
    client = await _get_authenticated_client(ctx, resolved_workspace)

    task_filter_parts = [f"workspace={resolved_workspace}"]
    if list_id:
        task_filter_parts.append(f"list={list_id}")
    elif space_id:
        task_filter_parts.append(f"space={space_id}")
    task_filter = ", ".join(task_filter_parts)

    if list_id:
        result = await client.get_list_tasks(
            list_id=list_id,
            status=status,
            assignee=assignee,
            priority=priority,
            page_size=page_size,
            include_archived=include_archived,
        )
    elif space_id:
        result = await client.get_space_tasks(
            space_id=space_id,
            status=status,
            assignee=assignee,
            priority=priority,
            page_size=page_size,
        )
    else:
        raise ValueError("Either list_id or space_id must be provided")

    tasks = result.get("tasks", [])

    readable_parts = [f"Found {len(tasks)} task(s) for {task_filter}:"]
    for task in tasks:
        readable_parts.append(_format_task(task))

    structured: dict[str, Any] = {
        "workspace_id": resolved_workspace,
        "filter": task_filter,
        "count": len(tasks),
        "tasks": tasks,
        "page_size": page_size,
    }

    return CallToolResult(
        content=[TextContent(type="text", text="\n".join(readable_parts))],
        structuredContent=structured,
    )


async def create_task_tool(
    ctx: MCPToolContext,
    list_id: str,
    name: str,
    description: Optional[str] = None,
    priority: Optional[str] = None,
    status: Optional[str] = None,
    assignee: Optional[str] = None,
    due_date: Optional[str] = None,
    workspace_id: Optional[str] = None,
) -> CallToolResult:
    resolved_workspace = await _resolve_workspace(ctx, workspace_id)
    client = await _get_authenticated_client(ctx, resolved_workspace)

    result = await client.create_task(
        list_id=list_id,
        name=name,
        description=description or "",
        priority=priority,
        status=status,
        assignee=assignee,
        due_date=due_date,
    )

    readable = (
        f"Task created successfully!\n"
        f"  ID: {result.get('id', 'N/A')}\n"
        f"  Name: {result.get('name', 'N/A')}\n"
        f"  List: {list_id}\n"
        f"  Workspace: {resolved_workspace}\n"
        f"  Status: {result.get('status', 'N/A')}\n"
        f"  Priority: {result.get('priority', 'N/A')}\n"
    )

    structured: dict[str, Any] = {
        "success": True,
        "task": result,
        "list_id": list_id,
        "workspace_id": resolved_workspace,
    }

    return CallToolResult(
        content=[TextContent(type="text", text=readable)],
        structuredContent=structured,
    )


def register_mcp_tools(
    mcp: FastMCP,
    ctx: MCPToolContext,
) -> None:
    async def _wrapper_list_tasks(**kwargs: Any) -> CallToolResult:
        return await list_tasks_tool(ctx, **kwargs)

    async def _wrapper_create_task(**kwargs: Any) -> CallToolResult:
        return await create_task_tool(ctx, **kwargs)

    mcp.add_tool(_wrapper_list_tasks, name="list_tasks")
    mcp.add_tool(_wrapper_create_task, name="create_task")
