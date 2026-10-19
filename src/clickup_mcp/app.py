from __future__ import annotations

import secrets
from contextlib import asynccontextmanager
from typing import Any, Optional

from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse
from starlette.responses import HTMLResponse

from clickup_mcp.config import Settings, get_settings
from clickup_mcp.crypto import encrypt_token, decrypt_token
from clickup_mcp.clickup_client import ClickUpClient, ClickUpAPIError
from clickup_mcp.storage import TokenStore
from clickup_mcp.tools import MCPToolContext, register_mcp_tools
from clickup_mcp.responses import (
    mcp_error_response,
    health_response,
    manifest_response,
    token_validation_response,
    oauth_authorization_response,
    oauth_token_response,
    oauth_error_response,
)
from clickup_mcp.errors import MCPError, AuthError


@asynccontextmanager
async def lifespan(app: FastAPI) -> Any:
    yield


def create_app(settings: Optional[Settings] = None) -> FastAPI:
    if settings is None:
        settings = get_settings()

    store = TokenStore(settings)
    tool_ctx = MCPToolContext(settings, store)
    clickup_client = ClickUpClient(settings)

    app = FastAPI(
        title=settings.APP_NAME,
        description=settings.APP_DESCRIPTION,
        version=settings.VERSION,
        lifespan=lifespan,
    )

    cors_origins = settings.CORS_ORIGINS
    if isinstance(cors_origins, str) and "*" in cors_origins:
        allow_origins = ["*"]
    else:
        allow_origins = [o.strip() for o in cors_origins.split(",")]

    app.add_middleware(
        CORSMiddleware,
        allow_origins=allow_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/health", tags=["health"])
    async def health() -> dict:
        return health_response()

    @app.get("/manifest", tags=["mcp"])
    async def manifest() -> dict:
        return manifest_response(settings)

    @app.get("/mcp/tools", tags=["mcp"])
    async def mcp_tools_info() -> dict:
        return {
            "tools": [
                {
                    "name": "list_tasks",
                    "description": "List tasks in a ClickUp space or list with filters",
                    "input_schema": {
                        "type": "object",
                        "properties": {
                            "list_id": {"type": "string", "description": "ClickUp list ID"},
                            "space_id": {"type": "string", "description": "ClickUp space ID"},
                            "workspace_id": {"type": "string", "description": "ClickUp workspace ID"},
                            "status": {"type": "string", "description": "Filter by status name"},
                            "assignee": {"type": "string", "description": "Filter by assignee ID"},
                            "priority": {"type": "string", "description": "Filter by priority (1=urgent, 2=high, 3=normal, 4=low)"},
                            "page_size": {"type": "integer", "description": "Number of results (1-100)", "default": 25},
                            "include_archived": {"type": "boolean", "description": "Include archived tasks", "default": False},
                        },
                    },
                },
                {
                    "name": "create_task",
                    "description": "Create a new task in a ClickUp list",
                    "input_schema": {
                        "type": "object",
                        "properties": {
                            "list_id": {"type": "string", "description": "ClickUp list ID to create task in"},
                            "name": {"type": "string", "description": "Task name"},
                            "description": {"type": "string", "description": "Task description"},
                            "priority": {"type": "string", "description": "Priority (1=urgent, 2=high, 3=normal, 4=low)"},
                            "status": {"type": "string", "description": "Initial status name"},
                            "assignee": {"type": "string", "description": "Assignee user ID"},
                            "due_date": {"type": "string", "description": "Due date (ISO 8601 format)"},
                            "workspace_id": {"type": "string", "description": "ClickUp workspace ID"},
                        },
                        "required": ["list_id", "name"],
                    },
                },
            ]
        }

    @app.get("/mcp", tags=["mcp"])
    async def mcp_endpoint(request: Request) -> dict:
        return {
            "mcp": "2024-11-05",
            "server": settings.APP_NAME,
            "tools_endpoint": "/mcp/tools",
            "description": settings.APP_DESCRIPTION,
        }

    @app.get("/token/validate", tags=["auth"])
    async def token_validate(request: Request) -> dict:
        persona_id = request.headers.get(settings.PERSONA_HEADER, "anonymous")
        workspace_id = request.query_params.get("workspace_id")

        if not workspace_id:
            return mcp_error_response(
                MCPError("missing_workspace_id", "workspace_id query parameter is required")
            )

        token_doc = await store.get_token(persona_id, workspace_id)
        if not token_doc:
            return token_validation_response(valid=False)

        try:
            decrypted_token = decrypt_token(
                token_doc["encrypted_token"],
                settings.ENCRYPTION_KEY,
                persona_id,
            )
        except Exception:
            return token_validation_response(valid=False)

        try:
            client = ClickUpClient(settings)
            client._access_token = decrypted_token
            team_info = await client.validate_token(decrypted_token)
            return token_validation_response(valid=True, team_info=team_info)
        except ClickUpAPIError:
            return token_validation_response(valid=False)

    @app.post("/token/settings", tags=["auth"])
    async def token_settings(request: Request) -> dict:
        persona_id = request.headers.get(settings.PERSONA_HEADER, "anonymous")
        try:
            body = await request.json()
        except Exception:
            return mcp_error_response(MCPError("invalid_body", "Request body is required"))

        workspace_id = body.get("workspace_id")
        api_token = body.get("api_token")

        if not workspace_id or not api_token:
            return mcp_error_response(
                MCPError("missing_fields", "workspace_id and api_token are required")
            )

        encrypted = encrypt_token(api_token, settings.ENCRYPTION_KEY, persona_id)
        await store.save_token(
            persona_id=persona_id,
            workspace_id=workspace_id,
            encrypted_token=encrypted,
        )

        return {
            "status": "saved",
            "workspace_id": workspace_id,
            "token_set": True,
        }

    @app.delete("/token/settings", tags=["auth"])
    async def token_remove(request: Request) -> dict:
        persona_id = request.headers.get(settings.PERSONA_HEADER, "anonymous")
        body: dict[str, Any] = {}
        try:
            body = await request.json()
        except Exception:
            pass

        workspace_id = body.get("workspace_id")
        if workspace_id:
            deleted = await store.delete_token(persona_id, workspace_id)
            return {"status": "removed" if deleted else "not_found", "workspace_id": workspace_id}
        else:
            tokens = await store.get_all_tokens(persona_id)
            for t in tokens:
                await store.delete_token(persona_id, t["workspace_id"])
            return {"status": "removed", "workspaces_removed": len(tokens)}

    @app.get("/project/schema", tags=["project"])
    async def project_schema(request: Request) -> dict:
        persona_id = request.headers.get(settings.PERSONA_HEADER, "anonymous")
        tokens = await store.get_all_tokens(persona_id)
        oauth_tokens = await store.get_oauth_tokens_by_persona(persona_id)

        token_list = []
        for t in tokens:
            token_list.append({
                "workspace_id": t["workspace_id"],
                "connected": True,
                "auth_type": "pat",
            })

        for t in oauth_tokens:
            ws_id = t["workspace_id"]
            if not any(ws["workspace_id"] == ws_id for ws in token_list):
                token_list.append({
                    "workspace_id": ws_id,
                    "connected": True,
                    "auth_type": "oauth2",
                })

        return {
            "persona_id": persona_id,
            "connected_workspaces": token_list,
            "schema": {
                "workspace_id": {"type": "string", "required": True, "description": "ClickUp workspace ID"},
                "api_token": {"type": "string", "required": False, "description": "ClickUp API token (Personal Access Token) - optional when using OAuth2"},
                "oauth2": {"type": "object", "required": False, "description": "OAuth2 authentication via ClickUp login flow"},
            },
            "oauth2_enabled": bool(settings.CLICKUP_OAUTH_CLIENT_ID),
        }

    @app.post("/project/connect", tags=["project"])
    async def project_connect(request: Request) -> dict:
        persona_id = request.headers.get(settings.PERSONA_HEADER, "anonymous")
        try:
            body = await request.json()
        except Exception:
            return mcp_error_response(MCPError("invalid_body", "Request body is required"))

        workspace_id = body.get("workspace_id")
        api_token = body.get("api_token")

        if not workspace_id:
            return mcp_error_response(MCPError("missing_workspace_id", "workspace_id is required"))

        if not api_token:
            return mcp_error_response(MCPError("missing_api_token", "api_token is required"))

        existing = await store.get_token(persona_id, workspace_id)
        if existing:
            return {
                "status": "already_connected",
                "workspace_id": workspace_id,
            }

        encrypted = encrypt_token(api_token, settings.ENCRYPTION_KEY, persona_id)
        await store.save_token(
            persona_id=persona_id,
            workspace_id=workspace_id,
            encrypted_token=encrypted,
        )

        return {
            "status": "connected",
            "workspace_id": workspace_id,
        }

    @app.post("/tools/list_tasks", tags=["tools"])
    async def tools_list_tasks(request: Request) -> Any:
        from clickup_mcp.tools.base import list_tasks_tool as _list_tasks
        try:
            body = await request.json()
        except Exception:
            return mcp_error_response(MCPError("invalid_body", "Request body is required"))

        persona_id = request.headers.get(settings.PERSONA_HEADER, "anonymous")
        tool_ctx._current_persona_id = persona_id
        result = await _list_tasks(tool_ctx, **body)
        return {
            "content": [c.model_dump() for c in result.content],
            "structured_content": result.structuredContent,
        }

    @app.post("/tools/create_task", tags=["tools"])
    async def tools_create_task(request: Request) -> Any:
        from clickup_mcp.tools.base import create_task_tool as _create_task
        try:
            body = await request.json()
        except Exception:
            return mcp_error_response(MCPError("invalid_body", "Request body is required"))

        persona_id = request.headers.get(settings.PERSONA_HEADER, "anonymous")
        tool_ctx._current_persona_id = persona_id
        result = await _create_task(tool_ctx, **body)
        return {
            "content": [c.model_dump() for c in result.content],
            "structured_content": result.structuredContent,
        }

    @app.get("/auth/login", tags=["auth"])
    async def auth_login(request: Request) -> dict:
        persona_id = request.headers.get(settings.PERSONA_HEADER, "anonymous")
        workspace_id = request.query_params.get("workspace_id", "")

        if not settings.CLICKUP_OAUTH_CLIENT_ID or not settings.CLICKUP_OAUTH_CLIENT_SECRET:
            return mcp_error_response(AuthError(
                "oauth_not_configured",
                "OAuth2 is not configured. Set CLICKUP_OAUTH_CLIENT_ID and CLICKUP_OAUTH_CLIENT_SECRET.",
            ))

        if not settings.CLICKUP_OAUTH_REDIRECT_URI:
            return mcp_error_response(AuthError(
                "oauth_not_configured",
                "OAuth2 redirect URI is not configured.",
            ))

        state = secrets.token_urlsafe(32)
        await store.save_session(state, {
            "persona_id": persona_id,
            "workspace_id": workspace_id,
        })

        auth_url = await clickup_client.get_oauth_authorization_url(
            state=state,
            redirect_uri=settings.CLICKUP_OAUTH_REDIRECT_URI,
            client_id=settings.CLICKUP_OAUTH_CLIENT_ID,
        )

        return oauth_authorization_response(auth_url, state)

    @app.get("/auth/callback", tags=["auth"])
    async def auth_callback(request: Request) -> dict:
        code = request.query_params.get("code")
        state = request.query_params.get("state")
        error = request.query_params.get("error")

        if error:
            error_desc = request.query_params.get("error_description", "Authorization failed")
            return oauth_error_response(error, error_desc)

        if not code or not state:
            return mcp_error_response(AuthError(
                "missing_params",
                "Authorization code and state are required.",
            ))

        session = await store.get_session(state)
        if not session:
            return mcp_error_response(AuthError(
                "invalid_state",
                "Invalid or expired authorization state.",
            ))

        persona_id = session["session_data"].get("persona_id", "anonymous")
        workspace_id = session["session_data"].get("workspace_id", "")

        await store.delete_session(state)

        if not settings.CLICKUP_OAUTH_CLIENT_ID or not settings.CLICKUP_OAUTH_CLIENT_SECRET:
            return mcp_error_response(AuthError(
                "oauth_not_configured",
                "OAuth2 is not configured.",
            ))

        try:
            token_data = await clickup_client.exchange_code_for_token(
                code=code,
                redirect_uri=settings.CLICKUP_OAUTH_REDIRECT_URI,
                client_id=settings.CLICKUP_OAUTH_CLIENT_ID,
                client_secret=settings.CLICKUP_OAUTH_CLIENT_SECRET,
            )
        except ClickUpAPIError as e:
            return mcp_error_response(AuthError(
                "token_exchange_failed",
                f"Failed to exchange authorization code: {e.message}",
            ))

        access_token = token_data.get("access_token", "")
        refresh_token = token_data.get("refresh_token", "")
        expires_in = token_data.get("expires_in", 3600)

        if access_token:
            encrypted_access = encrypt_token(
                access_token,
                settings.ENCRYPTION_KEY,
                f"{persona_id}:{workspace_id}",
            )

        if refresh_token:
            encrypted_refresh = encrypt_token(
                refresh_token,
                settings.ENCRYPTION_KEY,
                f"{persona_id}:{workspace_id}",
            )

        if access_token and refresh_token and workspace_id:
            await store.save_oauth_token(
                persona_id=persona_id,
                workspace_id=workspace_id,
                encrypted_access_token=encrypted_access,
                encrypted_refresh_token=encrypted_refresh,
                expires_at=expires_in,
            )

        return oauth_token_response(
            access_token_set=bool(access_token),
            workspace_id=workspace_id or "unknown",
            expires_in=expires_in,
        )

    @app.post("/auth/logout", tags=["auth"])
    async def auth_logout(request: Request) -> dict:
        persona_id = request.headers.get(settings.PERSONA_HEADER, "anonymous")
        body: dict[str, Any] = {}
        try:
            body = await request.json()
        except Exception:
            pass

        workspace_id = body.get("workspace_id")

        if settings.CLICKUP_OAUTH_CLIENT_ID and settings.CLICKUP_OAUTH_CLIENT_SECRET:
            try:
                if workspace_id:
                    token_doc = await store.get_oauth_token(persona_id, workspace_id)
                    if token_doc:
                        refresh_token = decrypt_token(
                            token_doc["encrypted_refresh_token"],
                            settings.ENCRYPTION_KEY,
                            f"{persona_id}:{workspace_id}",
                        )
                        await clickup_client.revoke_token(
                            token=refresh_token,
                            client_id=settings.CLICKUP_OAUTH_CLIENT_ID,
                            client_secret=settings.CLICKUP_OAUTH_CLIENT_SECRET,
                        )
                else:
                    all_tokens = await store.get_oauth_tokens_by_persona(persona_id)
                    for t in all_tokens:
                        ws = t["workspace_id"]
                        try:
                            rt = decrypt_token(
                                t["encrypted_refresh_token"],
                                settings.ENCRYPTION_KEY,
                                f"{persona_id}:{ws}",
                            )
                            await clickup_client.revoke_token(
                                token=rt,
                                client_id=settings.CLICKUP_OAUTH_CLIENT_ID,
                                client_secret=settings.CLICKUP_OAUTH_CLIENT_SECRET,
                            )
                        except Exception:
                            pass
                await store.delete_all_oauth_tokens(persona_id)
            except Exception:
                pass

        if workspace_id:
            await store.delete_token(persona_id, workspace_id)
            await store.delete_oauth_token(persona_id, workspace_id)
            return {"status": "logged_out", "workspace_id": workspace_id}
        else:
            tokens = await store.get_all_tokens(persona_id)
            for t in tokens:
                await store.delete_token(persona_id, t["workspace_id"])
            removed = await store.delete_all_oauth_tokens(persona_id)
            return {"status": "logged_out", "oauth_tokens_revoked": removed}

    @app.post("/auth/refresh", tags=["auth"])
    async def auth_refresh(request: Request) -> dict:
        persona_id = request.headers.get(settings.PERSONA_HEADER, "anonymous")
        try:
            body = await request.json()
        except Exception:
            return mcp_error_response(MCPError("invalid_body", "Request body is required"))

        workspace_id = body.get("workspace_id")
        if not workspace_id:
            return mcp_error_response(MCPError("missing_workspace_id", "workspace_id is required"))

        if not settings.CLICKUP_OAUTH_CLIENT_ID or not settings.CLICKUP_OAUTH_CLIENT_SECRET:
            return mcp_error_response(AuthError(
                "oauth_not_configured",
                "OAuth2 is not configured.",
            ))

        token_doc = await store.get_oauth_token(persona_id, workspace_id)
        if not token_doc:
            return oauth_error_response("no_token", f"No OAuth token found for workspace {workspace_id}")

        try:
            refresh_token = decrypt_token(
                token_doc["encrypted_refresh_token"],
                settings.ENCRYPTION_KEY,
                f"{persona_id}:{workspace_id}",
            )
        except Exception:
            return oauth_error_response("decrypt_failed", "Failed to decrypt refresh token")

        try:
            new_token_data = await clickup_client.refresh_access_token(
                refresh_token=refresh_token,
                client_id=settings.CLICKUP_OAUTH_CLIENT_ID,
                client_secret=settings.CLICKUP_OAUTH_CLIENT_SECRET,
            )
        except ClickUpAPIError as e:
            return oauth_error_response("refresh_failed", f"Failed to refresh token: {e.message}")

        new_access = new_token_data.get("access_token", "")
        new_refresh = new_token_data.get("refresh_token", refresh_token)
        new_expires_in = new_token_data.get("expires_in", 3600)

        if new_access:
            encrypted_access = encrypt_token(
                new_access,
                settings.ENCRYPTION_KEY,
                f"{persona_id}:{workspace_id}",
            )
            encrypted_refresh_new = encrypt_token(
                new_refresh,
                settings.ENCRYPTION_KEY,
                f"{persona_id}:{workspace_id}",
            )
            await store.save_oauth_token(
                persona_id=persona_id,
                workspace_id=workspace_id,
                encrypted_access_token=encrypted_access,
                encrypted_refresh_token=encrypted_refresh_new,
                expires_at=new_expires_in,
            )

        return oauth_token_response(
            access_token_set=bool(new_access),
            workspace_id=workspace_id,
            expires_in=new_expires_in,
        )

    @app.get("/ui", tags=["ui"])
    async def ui() -> HTMLResponse:
        return HTMLResponse(content=UI_TEMPLATE)

    @app.get("/ui/config", tags=["ui"])
    async def ui_config(request: Request) -> dict:
        persona_id = request.headers.get(settings.PERSONA_HEADER, "anonymous")
        tokens = await store.get_all_tokens(persona_id)
        workspaces = [{"workspace_id": t["workspace_id"]} for t in tokens]
        return {"workspaces": workspaces}

    @app.exception_handler(MCPError)
    async def mcp_error_handler(request: Request, exc: MCPError) -> JSONResponse:
        return mcp_error_response(exc)

    @app.exception_handler(ValueError)
    async def value_error_handler(request: Request, exc: ValueError) -> JSONResponse:
        return mcp_error_response(MCPError("validation_error", str(exc)))

    return app


UI_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>ClickUpMCP</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #1a1a2e; color: #e0e0e0; min-height: 100vh; }
        .container { max-width: 800px; margin: 0 auto; padding: 2rem; }
        h1 { color: #7c3aed; margin-bottom: 0.5rem; }
        h2 { color: #a78bfa; margin: 1.5rem 0 0.5rem; font-size: 1.2rem; }
        .subtitle { color: #888; margin-bottom: 2rem; }
        .card { background: #16213e; border-radius: 8px; padding: 1.5rem; margin-bottom: 1.5rem; border: 1px solid #2a2a4a; }
        label { display: block; margin-bottom: 0.3rem; color: #aaa; font-size: 0.9rem; }
        select, input, textarea { width: 100%; padding: 0.6rem; margin-bottom: 1rem; background: #0f1629; border: 1px solid #2a2a4a; border-radius: 4px; color: #e0e0e0; font-size: 0.95rem; }
        select:focus, input:focus, textarea:focus { outline: none; border-color: #7c3aed; }
        button { background: #7c3aed; color: white; border: none; padding: 0.7rem 1.5rem; border-radius: 4px; cursor: pointer; font-size: 0.95rem; margin-right: 0.5rem; margin-bottom: 0.5rem; }
        button:hover { background: #6d28d9; }
        button.secondary { background: #374151; }
        button.secondary:hover { background: #4b5563; }
        button.danger { background: #dc2626; }
        button.danger:hover { background: #b91c1c; }
        pre { background: #0f1629; padding: 1rem; border-radius: 4px; overflow-x: auto; font-size: 0.85rem; max-height: 400px; overflow-y: auto; }
        .tabs { display: flex; gap: 0.5rem; margin-bottom: 1.5rem; }
        .tab { padding: 0.5rem 1rem; background: #16213e; border: 1px solid #2a2a4a; border-radius: 4px; cursor: pointer; color: #888; }
        .tab.active { background: #7c3aed; color: white; border-color: #7c3aed; }
        .tab-content { display: none; }
        .tab-content.active { display: block; }
        .status { padding: 0.5rem 1rem; border-radius: 4px; margin-top: 0.5rem; font-size: 0.9rem; }
        .status.success { background: #065f46; color: #6ee7b7; }
        .status.error { background: #7f1d1d; color: #fca5a5; }
        .workspaces-list { max-height: 200px; overflow-y: auto; }
        .workspace-item { display: flex; justify-content: space-between; align-items: center; padding: 0.5rem; border-bottom: 1px solid #2a2a4a; }
        .api-token-input { border-color: #f59e0b; }
    </style>
</head>
<body>
    <div class="container">
        <h1>ClickUpMCP</h1>
        <p class="subtitle">Integrates ClickUp tasks, spaces, lists, and updates.</p>

        <div class="tabs">
            <div class="tab active" onclick="showTab('connect')">Connect</div>
            <div class="tab" onclick="showTab('list')">List Tasks</div>
            <div class="tab" onclick="showTab('create')">Create Task</div>
        </div>

        <div id="tab-connect" class="tab-content active">
            <div class="card">
                <h2>Connect Workspace</h2>
                <p style="margin-bottom:1rem; color:#888;">Enter your ClickUp API token to connect a workspace.</p>
                <label for="connect-workspace">Workspace ID</label>
                <input type="text" id="connect-workspace" placeholder="e.g., abc123">
                <label for="connect-api-token">API Token</label>
                <input type="password" id="connect-api-token" class="api-token-input" placeholder="Your ClickUp Personal Access Token">
                <button onclick="connectWorkspace()" id="connect-btn">Connect</button>
                <div id="connect-status"></div>
            </div>
            <div class="card">
                <h2>Connected Workspaces</h2>
                <div class="workspaces-list" id="workspaces-list"></div>
            </div>
        </div>

        <div id="tab-list" class="tab-content">
            <div class="card">
                <h2>List Tasks</h2>
                <label for="list-workspace">Workspace</label>
                <select id="list-workspace"></select>
                <label for="list-list-id">List ID (optional)</label>
                <input type="text" id="list-list-id" placeholder="e.g., abc123">
                <label for="list-space-id">Space ID (optional, if no list)</label>
                <input type="text" id="list-space-id" placeholder="e.g., def456">
                <label for="list-status">Status filter</label>
                <input type="text" id="list-status" placeholder="e.g., done">
                <label for="list-priority">Priority filter (1=urgent, 2=high, 3=normal, 4=low)</label>
                <input type="text" id="list-priority" placeholder="e.g., 2">
                <button onclick="listTasks()" id="list-btn">List Tasks</button>
                <div id="list-status"></div>
                <pre id="list-results" style="display:none;"></pre>
            </div>
        </div>

        <div id="tab-create" class="tab-content">
            <div class="card">
                <h2>Create Task</h2>
                <label for="create-workspace">Workspace</label>
                <select id="create-workspace"></select>
                <label for="create-list-id">List ID *</label>
                <input type="text" id="create-list-id" placeholder="e.g., abc123">
                <label for="create-name">Task Name *</label>
                <input type="text" id="create-name" placeholder="Enter task name">
                <label for="create-description">Description</label>
                <textarea id="create-description" rows="3" placeholder="Task description"></textarea>
                <label for="create-priority">Priority (1=urgent, 2=high, 3=normal, 4=low)</label>
                <input type="text" id="create-priority" placeholder="e.g., 3">
                <label for="create-status">Status</label>
                <input type="text" id="create-status" placeholder="e.g., not_started">
                <label for="create-assignee">Assignee ID</label>
                <input type="text" id="create-assignee" placeholder="e.g., user123">
                <label for="create-due-date">Due Date (ISO 8601)</label>
                <input type="text" id="create-due-date" placeholder="e.g., 2025-12-31">
                <button onclick="createTask()" id="create-btn">Create Task</button>
                <div id="create-status"></div>
                <pre id="create-results" style="display:none;"></pre>
            </div>
        </div>
    </div>

    <script>
    const API_BASE = window.location.origin;

    function showTab(name) {
        document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
        document.querySelectorAll('.tab-content').forEach(t => t.classList.remove('active'));
        document.getElementById('tab-' + name).classList.add('active');
        event.target.classList.add('active');
        if (name !== 'connect') loadWorkspaces();
    }

    function setStatus(id, message, type) {
        const el = document.getElementById(id);
        el.className = 'status ' + type;
        el.textContent = message;
        setTimeout(() => { el.textContent = ''; el.className = ''; }, 5000);
    }

    async function connectWorkspace() {
        const workspaceId = document.getElementById('connect-workspace').value;
        const apiToken = document.getElementById('connect-api-token').value;

        if (!workspaceId || !apiToken) {
            setStatus('connect-status', 'Workspace ID and API Token are required.', 'error');
            return;
        }

        try {
            const res = await fetch(API_BASE + '/project/connect', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({workspace_id: workspaceId, api_token: apiToken})
            });
            const data = await res.json();
            if (data.status === 'connected' || data.status === 'already_connected') {
                setStatus('connect-status', 'Workspace connected successfully!', 'success');
                document.getElementById('connect-workspace').value = '';
                document.getElementById('connect-api-token').value = '';
                loadWorkspaces();
            } else {
                setStatus('connect-status', 'Failed to connect workspace.', 'error');
            }
        } catch (e) {
            setStatus('connect-status', 'Error: ' + e.message, 'error');
        }
    }

    async function loadWorkspaces() {
        try {
            const res = await fetch(API_BASE + '/project/schema');
            const data = await res.json();
            const list = document.getElementById('workspaces-list');
            const selects = [document.getElementById('list-workspace'), document.getElementById('create-workspace')];

            list.innerHTML = '';
            selects.forEach(s => { s.innerHTML = ''; });

            data.connected_workspaces.forEach(ws => {
                list.innerHTML += '<div class="workspace-item">' +
                    '<span>' + ws.workspace_id + '</span>' +
                    '<button class="danger" style="padding:0.3rem 0.6rem;font-size:0.8rem;" onclick="disconnectWorkspace(\\'' + ws.workspace_id + '\\')">Disconnect</button>' +
                    '</div>';
                selects.forEach(s => {
                    const opt = document.createElement('option');
                    opt.value = ws.workspace_id;
                    opt.textContent = ws.workspace_id;
                    s.appendChild(opt);
                });
            });
        } catch (e) {
            console.error('Failed to load workspaces:', e);
        }
    }

    async function disconnectWorkspace(workspaceId) {
        try {
            await fetch(API_BASE + '/token/settings', {
                method: 'DELETE',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({workspace_id: workspaceId})
            });
            loadWorkspaces();
            setStatus('connect-status', 'Workspace disconnected.', 'success');
        } catch (e) {
            setStatus('connect-status', 'Failed to disconnect.', 'error');
        }
    }

    async function listTasks() {
        const btn = document.getElementById('list-btn');
        btn.disabled = true;
        btn.textContent = 'Loading...';
        try {
            const body = {
                workspace_id: document.getElementById('list-workspace').value,
                list_id: document.getElementById('list-list-id').value || undefined,
                space_id: document.getElementById('list-space-id').value || undefined,
                status: document.getElementById('list-status').value || undefined,
                priority: document.getElementById('list-priority').value || undefined,
            };
            const res = await fetch(API_BASE + '/tools/list_tasks', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify(body)
            });
            const data = await res.json();
            const results = document.getElementById('list-results');
            results.style.display = 'block';
            results.textContent = JSON.stringify(data, null, 2);
            setStatus('list-status', 'Tasks loaded successfully.', 'success');
        } catch (e) {
            setStatus('list-status', 'Error: ' + e.message, 'error');
        } finally {
            btn.disabled = false;
            btn.textContent = 'List Tasks';
        }
    }

    async function createTask() {
        const btn = document.getElementById('create-btn');
        btn.disabled = true;
        btn.textContent = 'Creating...';
        try {
            const body = {
                workspace_id: document.getElementById('create-workspace').value,
                list_id: document.getElementById('create-list-id').value,
                name: document.getElementById('create-name').value,
                description: document.getElementById('create-description').value || undefined,
                priority: document.getElementById('create-priority').value || undefined,
                status: document.getElementById('create-status').value || undefined,
                assignee: document.getElementById('create-assignee').value || undefined,
                due_date: document.getElementById('create-due-date').value || undefined,
            };
            const res = await fetch(API_BASE + '/tools/create_task', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify(body)
            });
            const data = await res.json();
            const results = document.getElementById('create-results');
            results.style.display = 'block';
            results.textContent = JSON.stringify(data, null, 2);
            setStatus('create-status', 'Task created successfully!', 'success');
        } catch (e) {
            setStatus('create-status', 'Error: ' + e.message, 'error');
        } finally {
            btn.disabled = false;
            btn.textContent = 'Create Task';
        }
    }

    loadWorkspaces();
    </script>
</body>
</html>"""
