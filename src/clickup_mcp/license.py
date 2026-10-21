"""License watcher — placeholder for Twynity license validation."""

import asyncio
from logging import getLogger

from clickup_mcp.config import settings

logger = getLogger(__name__)


async def license_watcher():
    if not settings.LICENSE_KEY:
        return
    while True:
        await asyncio.sleep(86400)
