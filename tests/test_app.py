"""Tests for the FastMCP app endpoints."""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from starlette.testclient import TestClient

from clickup_mcp.config import Settings
from clickup_mcp.crypto import encrypt_token


def _make_settings(**overrides):
    base = {
        "CLICKUP_API_TOKEN": "test-api-token",
        "ENCRYPTION_KEY": "l2G_gvqENw5Xdptya18vB8IyK7yEbZiLI4PtCP-6lGE",
        "MONGODB_URI": "mongodb://localhost:27017",
    }
    base.update(overrides)
    return Settings(**base)


class TestHealthEndpoint:
    @pytest.fixture
    def client(self):
        with patch("clickup_mcp.storage.AsyncMongoClient"):
            from clickup_mcp.main import mcp
            yield TestClient(mcp.http_app())

    def test_health(self, client):
        resp = client.get("/api/v1/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"


class TestManifestEndpoint:
    @pytest.fixture
    def client(self):
        with patch("clickup_mcp.storage.AsyncMongoClient"):
            from clickup_mcp.main import mcp
            yield TestClient(mcp.http_app())

    def test_manifest(self, client):
        resp = client.get("/api/v1/.well-known/mcp.json")
        assert resp.status_code == 200
        data = resp.json()
        assert "Clickup" in data["name"]
        assert data["version"] == "1.0.0"
        assert data["mcp_version"] == "2024-11-05"


class TestOAuthLoginEndpoint:
    @pytest.fixture
    def client(self):
        with patch("clickup_mcp.storage.AsyncMongoClient"):
            from clickup_mcp.main import mcp
            yield TestClient(mcp.http_app())

    def test_login_oauth_not_configured(self, client):
        resp = client.get("/api/v1/auth/clickup/login")
        assert resp.status_code == 400
        data = resp.json()
        assert data["error"]["code"] == "oauth_not_configured"
