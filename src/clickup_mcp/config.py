import base64
import logging
from typing import Optional

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)


class Settings(BaseSettings):
    APP_NAME: str = "ClickUpMCP"
    APP_DESCRIPTION: str = "Integrates ClickUp tasks, spaces, lists, and updates."
    VERSION: str = "1.0.0"

    CLICKUP_API_BASE: str = "https://api.clickup.com/api/v2"

    CLICKUP_API_TOKEN: str = Field(default="", alias="CLICKUP_API_TOKEN")

    # OAuth2 settings
    CLICKUP_OAUTH_CLIENT_ID: str = Field(default="", alias="CLICKUP_OAUTH_CLIENT_ID")
    CLICKUP_OAUTH_CLIENT_SECRET: str = Field(default="", alias="CLICKUP_OAUTH_CLIENT_SECRET")
    CLICKUP_OAUTH_REDIRECT_URI: str = Field(default="", alias="CLICKUP_OAUTH_REDIRECT_URI")
    CLICKUP_OAUTH_AUTH_BASE_URL: str = "https://app.clickup.com"
    CLICKUP_OAUTH_TOKEN_URL: str = "https://api.clickup.com/api/v2/oauth/token"
    CLICKUP_OAUTH_SCOPES: str = "open"
    CLICKUP_OAUTH_REVOKE_URL: str = "https://api.clickup.com/api/v2/oauth/revoke"

    MONGODB_URI: str = "mongodb://localhost:27017"
    MONGODB_DB_NAME: str = "clickup_mcp"
    MONGODB_COLLECTION: str = "api_tokens"
    MONGODB_OAUTH_COLLECTION: str = "oauth_tokens"
    MONGODB_SESSION_COLLECTION: str = "oauth_sessions"

    ENCRYPTION_KEY: str = Field(default="", alias="ENCRYPTION_KEY")

    HOST: str = "0.0.0.0"
    PORT: int = 8000

    CORS_ORIGINS: str = "*"

    PERSONA_HEADER: str = "X-Persona-ID"

    model_config = SettingsConfigDict(
        env_prefix="",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


def get_settings() -> Settings:
    return Settings()


def validate_settings(settings: Settings) -> bool:
    valid = True
    if not settings.ENCRYPTION_KEY:
        logger.warning("ENCRYPTION_KEY is not set")
        valid = False
    if not settings.CLICKUP_API_TOKEN:
        logger.info(
            "CLICKUP_API_TOKEN not set at startup; tokens must be provided "
            "via /project/connect or /token/settings at runtime"
        )
    return valid


def validate_decoded_key(encryption_key: str) -> bool:
    """Validate that ENCRYPTION_KEY decodes to 16, 24, or 32 bytes.

    The key is decoded from URL-safe base64 first, then the decoded byte
    length is checked.  Handles missing padding.  Returns True if valid,
    False otherwise.
    """
    try:
        # Add padding if missing
        padding = 4 - len(encryption_key) % 4
        if padding != 4:
            encryption_key += "=" * padding
        decoded = base64.urlsafe_b64decode(encryption_key)
        return len(decoded) in (16, 24, 32)
    except Exception:
        return False
