"""Run the ClickUp MCP server."""

import uvicorn

from clickup_mcp.config import settings

if __name__ == "__main__":
    uvicorn.run(
        "clickup_mcp.main:app",
        host=settings.API_V1_STR.lstrip("/"),  # fallback
        port=8000,
        log_level="info",
    )
