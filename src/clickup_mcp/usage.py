"""Forward authenticated tool-call usage to Twynity's reporting service."""

import asyncio
import httpx
from logging import getLogger

from clickup_mcp.config import settings

logger = getLogger(__name__)


async def save_usage_report(method: str, endpoint: str, auth_header: str | None) -> None:
    if not settings.USAGE_REPORT_ENDPOINT:
        return
    if not auth_header:
        return
    try:
        data = {
            "service": settings.SERVICE_ID,
            "method": method,
            "endpoint": endpoint,
        }
        async with httpx.AsyncClient(timeout=5) as client:
            await client.post(settings.USAGE_REPORT_ENDPOINT, json=data, headers={"Authorization": auth_header})
    except Exception:
        logger.exception("Usage report failed — continuing")
