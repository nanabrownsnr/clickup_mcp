"""Twynity discovery, health, and ClickUp OAuth routes.

OAuth endpoints follow the Twynity convention. The user connects ClickUp
in Twynity UI; the browser flow lands the token here and we store it in
MongoDB scoped to (user_id, persona_id, workspace_id).

Routes (Twynity strips the /clickup service prefix before forwarding):
  GET  /api/v1/health
  GET  /api/v1/.well-known/mcp.json
  GET  /api/v1/auth/clickup/login
  POST /api/v1/callback
  POST /api/v1/auth/clickup/logout
"""

from __future__ import annotations

import secrets
from urllib.parse import parse_qs, urlparse

from starlette.requests import Request
from starlette.responses import JSONResponse

from clickup_mcp.auth import get_identity_from_headers, TwynityIdentity
from clickup_mcp.clickup_client import ClickUpClient, ClickUpAPIError
from clickup_mcp.config import settings
from clickup_mcp.crypto import decrypt_token, encrypt_token
from clickup_mcp.errors import AuthError
from clickup_mcp.responses import (
    mcp_error_response,
    oauth_authorization_response,
    oauth_error_response,
    oauth_token_response,
)
from clickup_mcp.storage import get_active_store
from clickup_mcp.tools.base import _set_current_identity


def _get_store():
    store = get_active_store()
    if store is None:
        raise RuntimeError("Connection storage is not available")
    return store


def _query(request: Request) -> dict:
    qs = parse_qs(urlparse(str(request.url)).query)
    return {k: v[0] for k, v in qs.items() if v}


async def _identity(request: Request) -> TwynityIdentity:
    """Resolve (user_id, persona_id) from the request JWT + header."""
    return await get_identity_from_headers(request.headers)


def register_routes(mcp):
    @mcp.custom_route("/api/v1/health", methods=["GET"])
    async def health_status(request: Request) -> JSONResponse:
        return JSONResponse({"status": "ok"})

    @mcp.custom_route("/api/v1/.well-known/mcp.json", methods=["GET"])
    async def manifest(request: Request) -> JSONResponse:
        return JSONResponse({
            "name": settings.APP_TITLE,
            "base_url": settings.PUBLIC_URL.rstrip("/") + "/mcp",
            "version": settings.VERSION,
            "mcp_version": "2024-11-05",
            "external_connections": {"project": {"name": "mcp_configuration"}},
        })

    @mcp.custom_route("/api/v1/auth/clickup/login", methods=["GET"])
    async def auth_login(request: Request) -> JSONResponse:
        identity = await _identity(request)
        query = _query(request)
        workspace_id = query.get("workspace_id", "")

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

        store = _get_store()
        state = secrets.token_urlsafe(32)
        await store.save_session(state, {
            "user_id": identity.user_id,
            "persona_id": identity.persona_id,
            "workspace_id": workspace_id,
        })

        client = ClickUpClient(settings)
        auth_url = await client.get_oauth_authorization_url(
            state=state,
            redirect_uri=settings.CLICKUP_OAUTH_REDIRECT_URI,
            client_id=settings.CLICKUP_OAUTH_CLIENT_ID,
        )
        return oauth_authorization_response(auth_url, state)

    @mcp.custom_route("/api/v1/callback", methods=["POST", "GET"])
    async def auth_callback(request: Request) -> JSONResponse:
        query = _query(request)
        code = query.get("code")
        state = query.get("state")
        error = query.get("error")

        if error:
            error_desc = query.get("error_description", "Authorization failed")
            return oauth_error_response(error, error_desc)
        if not code or not state:
            return mcp_error_response(AuthError(
                "missing_params",
                "Authorization code and state are required.",
            ))

        store = _get_store()
        session = await store.get_session(state)
        if not session:
            return mcp_error_response(AuthError(
                "invalid_state",
                "Invalid or expired authorization state.",
            ))
        user_id = session["session_data"].get("user_id", "anonymous")
        persona_id = session["session_data"].get("persona_id", "anonymous")
        workspace_id = session["session_data"].get("workspace_id", "")
        await store.delete_session(state)

        if not settings.CLICKUP_OAUTH_CLIENT_ID or not settings.CLICKUP_OAUTH_CLIENT_SECRET:
            return mcp_error_response(AuthError("oauth_not_configured", "OAuth2 is not configured."))

        client = ClickUpClient(settings)
        try:
            token_data = await client.exchange_code_for_token(
                code=code,
                redirect_uri=settings.CLICKUP_OAUTH_REDIRECT_URI,
                client_id=settings.CLICKUP_OAUTH_CLIENT_ID,
                client_secret=settings.CLICKUP_OAUTH_CLIENT_SECRET,
            )
        except ClickUpAPIError as e:
            return mcp_error_response(AuthError(
                "token_exchange_failed",
                "Failed to exchange authorization code: " + e.message,
            ))

        access_token = token_data.get("access_token", "")
        refresh_token = token_data.get("refresh_token", "")
        expires_in = token_data.get("expires_in", 3600)

        encrypted_access = None
        encrypted_refresh = None
        if access_token:
            encrypted_access = encrypt_token(
                access_token, settings.ENCRYPTION_KEY, persona_id + ":" + workspace_id,
            )
        if refresh_token:
            encrypted_refresh = encrypt_token(
                refresh_token, settings.ENCRYPTION_KEY, persona_id + ":" + workspace_id,
            )

        if access_token and refresh_token and workspace_id:
            await store.save_oauth_token(
                user_id=user_id,
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

    @mcp.custom_route("/api/v1/auth/clickup/logout", methods=["POST"])
    async def auth_logout(request: Request) -> JSONResponse:
        identity = await _identity(request)
        user_id = identity.user_id
        persona_id = identity.persona_id
        body = {}
        try:
            body = await request.json()
        except Exception:
            pass
        workspace_id = body.get("workspace_id")

        store = _get_store()
        client = ClickUpClient(settings)
        if settings.CLICKUP_OAUTH_CLIENT_ID and settings.CLICKUP_OAUTH_CLIENT_SECRET:
            try:
                if workspace_id:
                    token_doc = await store.get_oauth_token(user_id, persona_id, workspace_id)
                    if token_doc:
                        refresh_token = decrypt_token(
                            token_doc["encrypted_refresh_token"],
                            settings.ENCRYPTION_KEY,
                            persona_id + ":" + workspace_id,
                        )
                        await client.revoke_token(
                            token=refresh_token,
                            client_id=settings.CLICKUP_OAUTH_CLIENT_ID,
                            client_secret=settings.CLICKUP_OAUTH_CLIENT_SECRET,
                        )
                else:
                    all_tokens = await store.get_oauth_tokens_by_persona(user_id, persona_id)
                    for t in all_tokens:
                        ws = t["workspace_id"]
                        try:
                            rt = decrypt_token(
                                t["encrypted_refresh_token"],
                                settings.ENCRYPTION_KEY,
                                persona_id + ":" + ws,
                            )
                            await client.revoke_token(
                                token=rt,
                                client_id=settings.CLICKUP_OAUTH_CLIENT_ID,
                                client_secret=settings.CLICKUP_OAUTH_CLIENT_SECRET,
                            )
                        except Exception:
                            pass
                await store.delete_all_oauth_tokens(user_id, persona_id)
            except Exception:
                pass

        if workspace_id:
            await store.delete_token(user_id, persona_id, workspace_id)
            await store.delete_oauth_token(user_id, persona_id, workspace_id)
            return JSONResponse({"status": "logged_out", "workspace_id": workspace_id})
        else:
            tokens = await store.get_all_tokens(user_id, persona_id)
            for t in tokens:
                await store.delete_token(user_id, persona_id, t["workspace_id"])
            removed = await store.delete_all_oauth_tokens(user_id, persona_id)
            return JSONResponse({"status": "logged_out", "oauth_tokens_revoked": removed})
