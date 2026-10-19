from __future__ import annotations

from typing import Any

from starlette.requests import Request
from starlette.responses import JSONResponse, HTMLResponse

from clickup_mcp.config import Settings
from clickup_mcp.errors import MCPError


def mcp_error_response(error: MCPError, status_code: int = 400) -> JSONResponse:
    body = {
        "error": {
            "code": error.code,
            "message": error.message,
        }
    }
    if error.detail:
        body["error"]["detail"] = error.detail
    return JSONResponse(status_code=status_code, content=body)


def health_response() -> dict:
    return {
        "status": "healthy",
        "service": "ClickUpMCP",
        "version": "1.0.0",
    }


def manifest_response(settings: Settings) -> dict:
    auth_type = "oauth2" if settings.CLICKUP_OAUTH_CLIENT_ID else "token"
    return {
        "name": settings.APP_NAME,
        "version": settings.VERSION,
        "description": settings.APP_DESCRIPTION,
        "mcp_version": "2024-11-05",
        "capabilities": {
            "tools": True,
            "resources": False,
            "prompts": False,
        },
        "auth": {
            "type": auth_type,
            "flow": "authorization_code" if auth_type == "oauth2" else "bearer",
            "scopes": settings.CLICKUP_OAUTH_SCOPES.split(",") if auth_type == "oauth2" else ["open"],
        },
    }


def token_validation_response(valid: bool, team_info: dict | None = None) -> dict:
    return {
        "valid": valid,
        "team": team_info,
    }


def oauth_authorization_response(authorization_url: str, state: str) -> dict:
    return {
        "authorization_url": authorization_url,
        "state": state,
        "status": "authorization_required",
    }


def oauth_token_response(
    access_token_set: bool,
    workspace_id: str,
    token_type: str = "Bearer",
    expires_in: int | None = None,
) -> dict:
    return {
        "access_token_set": access_token_set,
        "workspace_id": workspace_id,
        "token_type": token_type,
        "expires_in": expires_in,
        "status": "authenticated",
    }


def oauth_error_response(error: str, error_description: str | None = None, status_code: int = 400) -> JSONResponse:
    body: dict[str, Any] = {
        "error": {
            "code": error,
            "message": error_description or error,
        }
    }
    return JSONResponse(status_code=status_code, content=body)
