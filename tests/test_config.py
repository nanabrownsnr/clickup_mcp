from __future__ import annotations

import pytest
from clickup_mcp.config import Settings, get_settings, validate_settings


class TestSettings:
    def test_default_values(self):
        s = Settings(
            CLICKUP_API_TOKEN="test-token",
            ENCRYPTION_KEY="l2G_gvqENw5Xdptya18vB8IyK7yEbZiLI4PtCP-6lGE",
        )
        assert s.APP_NAME == "ClickUpMCP"
        assert s.APP_DESCRIPTION == "Integrates ClickUp tasks, spaces, lists, and updates."
        assert s.VERSION == "1.0.0"
        assert s.CLICKUP_API_BASE == "https://api.clickup.com/api/v2"
        assert s.HOST == "0.0.0.0"
        assert s.PORT == 8000
        assert s.MONGODB_COLLECTION == "api_tokens"

    def test_custom_values(self):
        s = Settings(
            CLICKUP_API_TOKEN="my-token",
            ENCRYPTION_KEY="me8oIy6lGBctWAPHudSKJg",
            MONGODB_URI="mongodb://myhost:27017",
            MONGODB_DB_NAME="mydb",
            PORT=9000,
        )
        assert s.CLICKUP_API_TOKEN == "my-token"
        assert s.MONGODB_URI == "mongodb://myhost:27017"
        assert s.MONGODB_DB_NAME == "mydb"
        assert s.PORT == 9000

    def test_validate_settings_missing_token(self):
        s = Settings(
            CLICKUP_API_TOKEN="",
            ENCRYPTION_KEY="l2G_gvqENw5Xdptya18vB8IyK7yEbZiLI4PtCP-6lGE",
        )
        assert validate_settings(s) is True

    def test_validate_settings_missing_encryption_key(self):
        s = Settings(
            CLICKUP_API_TOKEN="token",
            ENCRYPTION_KEY="",
        )
        assert validate_settings(s) is False

    def test_validate_settings_short_encryption_key(self):
        """Any non-empty encryption key length should pass validation."""
        s = Settings(
            CLICKUP_API_TOKEN="token",
            ENCRYPTION_KEY="short",
        )
        assert validate_settings(s) is True

    def test_validate_settings_valid(self):
        s = Settings(
            CLICKUP_API_TOKEN="valid-token",
            ENCRYPTION_KEY="l2G_gvqENw5Xdptya18vB8IyK7yEbZiLI4PtCP-6lGE",
        )
        assert validate_settings(s) is True

    def test_validate_settings_with_warnings(self):
        s = Settings(
            CLICKUP_API_TOKEN="",
            ENCRYPTION_KEY="",
        )
        result = validate_settings(s)
        assert result is False
        # Missing token is informational only; missing encryption key is failure

    def test_validate_settings_valid_24_byte_key(self):
        s = Settings(
            CLICKUP_API_TOKEN="token",
            ENCRYPTION_KEY="EhIRdKph9hjomdCAWML_IQr_euKo5TP1",
        )
        assert validate_settings(s) is True

    def test_validate_settings_valid_32_byte_key(self):
        s = Settings(
            CLICKUP_API_TOKEN="token",
            ENCRYPTION_KEY="l2G_gvqENw5Xdptya18vB8IyK7yEbZiLI4PtCP-6lGE",
        )
        assert validate_settings(s) is True

    def test_validate_settings_missing_both(self):
        s = Settings(
            CLICKUP_API_TOKEN="",
            ENCRYPTION_KEY="",
        )
        # Both missing: encryption key missing causes validation failure
        assert validate_settings(s) is False

    def test_validate_settings_runtime_token_mode(self):
        """Token provided at runtime via /project/connect, not at startup."""
        s = Settings(
            CLICKUP_API_TOKEN="",
            ENCRYPTION_KEY="l2G_gvqENw5Xdptya18vB8IyK7yEbZiLI4PtCP-6lGE",
        )
        assert validate_settings(s) is True
        assert s.CLICKUP_API_TOKEN == ""

    def test_settings_default_app_name(self):
        s = Settings(ENCRYPTION_KEY="l2G_gvqENw5Xdptya18vB8IyK7yEbZiLI4PtCP-6lGE")
        assert s.APP_NAME == "ClickUpMCP"
        assert s.APP_DESCRIPTION == "Integrates ClickUp tasks, spaces, lists, and updates."

    def test_settings_port_range(self):
        s = Settings(PORT=443, ENCRYPTION_KEY="l2G_gvqENw5Xdptya18vB8IyK7yEbZiLI4PtCP-6lGE")
        assert s.PORT == 443

    def test_settings_default_mongodb(self):
        s = Settings(ENCRYPTION_KEY="l2G_gvqENw5Xdptya18vB8IyK7yEbZiLI4PtCP-6lGE")
        assert s.MONGODB_URI == "mongodb://localhost:27017"
        assert s.MONGODB_DB_NAME == "clickup_mcp"
