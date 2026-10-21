"""Service identity, environment settings, and validation."""

from __future__ import annotations

import base64
import logging
import os
from typing import Optional

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)

# MCP name used for SERVICE_ID / APP_TITLE defaults.
mcp_name = "clickup"


def configured_mcp_name() -> str:
    return mcp_name.strip() or "clickup"


class Settings(BaseSettings):
    # Service identity
    SERVICE_ID: str = f"{configured_mcp_name()}_mcp"
    APP_TITLE: str = f"{configured_mcp_name().title()} MCP"
    APP_NAME: str = "ClickUpMCP"
    APP_DESCRIPTION: str = "Integrates ClickUp tasks, spaces, lists, and updates."
    APP_VERSION: str = "1.0.0"
    VERSION: str = "1.0.0"
    API_V1_STR: str = "/api/v1"
    PUBLIC_URL: str = "http://localhost:8000"
    RELEASE_ID: str = "1.0.0"

    # ClickUp API
    CLICKUP_API_BASE: str = "https://api.clickup.com/api/v2"
    CLICKUP_API_TOKEN: str = Field(default="", alias="CLICKUP_API_TOKEN")

    # OAuth2
    CLICKUP_OAUTH_CLIENT_ID: str = Field(default="", alias="CLICKUP_OAUTH_CLIENT_ID")
    CLICKUP_OAUTH_CLIENT_SECRET: str = Field(
        default="", alias="CLICKUP_OAUTH_CLIENT_SECRET"
    )
    CLICKUP_OAUTH_REDIRECT_URI: str = Field(
        default="", alias="CLICKUP_OAUTH_REDIRECT_URI"
    )
    CLICKUP_OAUTH_AUTH_BASE_URL: str = "https://app.clickup.com"
    CLICKUP_OAUTH_TOKEN_URL: str = "https://api.clickup.com/api/v2/oauth/token"
    CLICKUP_OAUTH_SCOPES: str = "open"
    CLICKUP_OAUTH_REVOKE_URL: str = "https://api.clickup.com/api/v2/oauth/revoke"

    # MongoDB
    MONGODB_URI: str = "mongodb://localhost:27017"
    MONGODB_DB_NAME: str = "clickup_mcp"
    MONGODB_COLLECTION: str = "api_tokens"
    MONGODB_OAUTH_COLLECTION: str = "oauth_tokens"
    MONGODB_SESSION_COLLECTION: str = "oauth_sessions"

    # Encryption
    ENCRYPTION_KEY: str = Field(default="", alias="ENCRYPTION_KEY")

    # Server
    HOST: str = "0.0.0.0"
    PORT: int = 8000

    # CORS
    ALLOWED_ORIGINS: str = "*"

    # Identity
    PERSONA_ID_HEADER: str = "Persona-Id"
    PERSONA_HEADER: str = "X-Persona-ID"

    # Twynity / Account Service
    ACCOUNT_SERVICE_URL: str = Field(default="", alias="ACCOUNT_SERVICE_URL")
    ACCOUNT_SERVICE_JWKS_ENDPOINT: str = Field(
        default="/.well-known/jwks.json", alias="ACCOUNT_SERVICE_JWKS_ENDPOINT"
    )

    # License
    LICENSE_KEY: str = Field(default="", alias="LICENSE_KEY")
    LICENSE_SERVER_BASE_URL: str = Field(default="", alias="LICENSE_SERVER_BASE_URL")
    LICENSE_SERVER_JWKS_ENDPOINT: str = Field(default="", alias="LICENSE_SERVER_JWKS_ENDPOINT")
    LICENSE_SERVER_ACTIVATION_ENDPOINT: str = Field(default="", alias="LICENSE_SERVER_ACTIVATION_ENDPOINT")

    # Usage reporting
    USAGE_REPORT_ENDPOINT: str = Field(default="", alias="USAGE_REPORT_ENDPOINT")

    model_config = SettingsConfigDict(
        env_prefix="",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()


def get_settings() -> Settings:
    return settings


def validate_settings(settings_obj: Settings) -> bool:
    valid = True
    if not settings_obj.ENCRYPTION_KEY:
        logger.warning("ENCRYPTION_KEY is not set")
        valid = False
    if not settings_obj.CLICKUP_API_TOKEN:
        logger.info(
            "CLICKUP_API_TOKEN not set at startup; tokens must be provided "
            "via /project/connect or /token/settings at runtime"
        )
    return valid


def validate_decoded_key(encryption_key: str) -> bool:
    """Validate that ENCRYPTION_KEY decodes to 16, 24, or 32 bytes."""
    try:
        padding = 4 - len(encryption_key) % 4
        if padding != 4:
            encryption_key += "=" * padding
        decoded = base64.urlsafe_b64decode(encryption_key)
        return len(decoded) in (16, 24, 32)
    except Exception:
        return False
