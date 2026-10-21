"""Compose and expose the FastMCP ASGI application."""

import asyncio
from contextlib import asynccontextmanager, suppress
from logging import getLogger

from fastmcp import FastMCP
from fastmcp.server.middleware import Middleware as MCPMiddleware
from fastmcp.server.middleware import MiddlewareContext
from pymongo import AsyncMongoClient
from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware

from clickup_mcp.config import settings
from clickup_mcp.license import license_watcher
from clickup_mcp.storage import TokenStore, set_active_store
from clickup_mcp.tools.base import register_mcp_tools, _set_current_identity
from clickup_mcp.twynity import register_routes
from clickup_mcp.usage import save_usage_report

logger = getLogger(__name__)


@asynccontextmanager
async def app_lifespan(server):
    mongo = AsyncMongoClient(settings.MONGODB_URI, serverSelectionTimeoutMS=5000)
    task = None
    try:
        store = TokenStore(settings)
        set_active_store(store)
        task = asyncio.create_task(license_watcher())
        yield
    finally:
        if task is not None:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
        set_active_store(None)
        await mongo.close()


mcp = FastMCP(
    settings.APP_TITLE,
    version=settings.VERSION,
    lifespan=app_lifespan,
)


class IdentityMiddleware(MCPMiddleware):
    """Set the per-request (user_id, persona_id) identity for tool calls."""

    async def on_call_tool(self, context: MiddlewareContext, call_next):
        try:
            headers = context.request.headers if context.request else {}
            persona_id = headers.get(settings.PERSONA_ID_HEADER.lower(), "anonymous")
            # user_id would come from the verified JWT; in unauthenticated
            # mode fall back to the persona header for scoping.
            user_id = headers.get("x-twynity-user-id", "anonymous")
            _set_current_identity(user_id, persona_id)
        except Exception:
            _set_current_identity("anonymous", "anonymous")
        return await call_next(context)


class UsageTrackingMiddleware(MCPMiddleware):
    async def on_call_tool(self, context: MiddlewareContext, call_next):
        try:
            auth = context.request.headers.get("authorization") if context.request else None
            await save_usage_report(
                method="TOOL_CALL",
                endpoint=context.message.name,
                auth_header=auth,
            )
        except Exception:
            logger.exception("Usage tracking failed")
        return await call_next(context)


mcp.add_middleware(IdentityMiddleware())
mcp.add_middleware(UsageTrackingMiddleware())

register_routes(mcp)
register_mcp_tools(mcp, settings)

origins = [o.strip() for o in settings.ALLOWED_ORIGINS.split(",") if o.strip()]
middleware_list = [
    Middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["mcp-session-id"],
    )
]

app = mcp.http_app(middleware=middleware_list)
