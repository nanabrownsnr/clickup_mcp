from __future__ import annotations

import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from starlette.testclient import TestClient

from clickup_mcp.config import Settings
from clickup_mcp.app import create_app
from clickup_mcp.crypto import encrypt_token


def _make_settings(**overrides) -> Settings:
    base = {
        "CLICKUP_API_TOKEN": "test-api-token",
        "ENCRYPTION_KEY": "l2G_gvqENw5Xdptya18vB8IyK7yEbZiLI4PtCP-6lGE",
        "MONGODB_URI": "mongodb://localhost:27017",
    }
    base.update(overrides)
    return Settings(**base)


def _make_mock_mongodb():
    mock_client = MagicMock()
    mock_db = MagicMock()
    mock_collection = MagicMock()
    mock_oauth_collection = MagicMock()
    mock_session_collection = MagicMock()

    mock_db.__getitem__ = MagicMock(side_effect=lambda key: {
        "api_tokens": mock_collection,
        "oauth_tokens": mock_oauth_collection,
        "oauth_sessions": mock_session_collection,
    }.get(key, MagicMock()))

    mock_client.__getitem__ = MagicMock(return_value=mock_db)
    mock_collection.create_index = MagicMock()
    mock_oauth_collection.create_index = MagicMock()
    mock_session_collection.create_index = MagicMock()
    mock_collection.save_token = AsyncMock()
    mock_collection.get_token = AsyncMock()
    mock_collection.get_all_tokens = AsyncMock()
    mock_collection.delete_token = AsyncMock(return_value=True)
    return mock_client, mock_db, mock_collection, mock_oauth_collection, mock_session_collection


class TestTokenValidation:
    def test_validate_missing_workspace_id(self):
        mock_client, mock_db, mock_collection, _, _ = _make_mock_mongodb()
        with patch("clickup_mcp.storage.MongoClient", return_value=mock_client):
            settings = _make_settings()
            app = create_app(settings)
            client = TestClient(app)
            resp = client.get("/token/validate")
            assert resp.status_code == 400
            data = resp.json()
            assert data["error"]["code"] == "missing_workspace_id"

    def test_validate_no_token_stored(self):
        mock_client, mock_db, mock_collection, _, _ = _make_mock_mongodb()
        mock_collection.find_one = MagicMock(return_value=None)
        with patch("clickup_mcp.storage.MongoClient", return_value=mock_client):
            settings = _make_settings()
            app = create_app(settings)
            client = TestClient(app)
            resp = client.get("/token/validate?workspace_id=ws-123")
            assert resp.status_code == 200
            data = resp.json()
            assert data["valid"] is False
            assert data["team"] is None

    def test_validate_invalid_token(self):
        mock_client, mock_db, mock_collection, _, _ = _make_mock_mongodb()
        mock_collection.find_one = MagicMock(return_value={
            "workspace_id": "ws-123",
            "encrypted_token": {
                "encrypted_token": "invalid-encrypted-data",
                "salt": "test-persona",
            },
        })
        with patch("clickup_mcp.storage.MongoClient", return_value=mock_client):
            with patch("clickup_mcp.clickup_client.ClickUpClient.validate_token", new_callable=AsyncMock) as mock_validate:
                from clickup_mcp.clickup_client import ClickUpAPIError
                mock_validate.side_effect = ClickUpAPIError(401, "Unauthorized")
                settings = _make_settings()
                app = create_app(settings)
                client = TestClient(app)
                resp = client.get(
                    "/token/validate?workspace_id=ws-123",
                    headers={"X-Persona-ID": "test-persona"}
                )
                assert resp.status_code == 200
                data = resp.json()
                assert data["valid"] is False

    def test_validate_valid_token(self):
        mock_client, mock_db, mock_collection, _, _ = _make_mock_mongodb()
        encrypted = encrypt_token("valid-api-token", "l2G_gvqENw5Xdptya18vB8IyK7yEbZiLI4PtCP-6lGE", "test-persona")
        mock_collection.find_one = MagicMock(return_value={
            "workspace_id": "ws-123",
            "encrypted_token": encrypted,
        })
        with patch("clickup_mcp.storage.MongoClient", return_value=mock_client):
            with patch("clickup_mcp.clickup_client.ClickUpClient.validate_token", new_callable=AsyncMock) as mock_validate:
                mock_validate.return_value = {"id": "team-123", "name": "Test Team"}
                settings = _make_settings()
                app = create_app(settings)
                client = TestClient(app)
                resp = client.get(
                    "/token/validate?workspace_id=ws-123",
                    headers={"X-Persona-ID": "test-persona"}
                )
                assert resp.status_code == 200
                data = resp.json()
                assert data["valid"] is True
                assert data["team"]["id"] == "team-123"
                assert data["team"]["name"] == "Test Team"


class TestTokenSettings:
    def test_save_token(self):
        mock_client, mock_db, mock_collection, _, _ = _make_mock_mongodb()
        mock_collection.replace_one = MagicMock()
        with patch("clickup_mcp.storage.MongoClient", return_value=mock_client):
            settings = _make_settings()
            app = create_app(settings)
            client = TestClient(app)
            resp = client.post(
                "/token/settings",
                json={"workspace_id": "ws-123", "api_token": "secret-token"},
                headers={"X-Persona-ID": "test-persona"}
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["status"] == "saved"
            assert data["workspace_id"] == "ws-123"
            assert data["token_set"] is True

    def test_save_token_missing_fields(self):
        mock_client, mock_db, mock_collection, _, _ = _make_mock_mongodb()
        with patch("clickup_mcp.storage.MongoClient", return_value=mock_client):
            settings = _make_settings()
            app = create_app(settings)
            client = TestClient(app)
            resp = client.post(
                "/token/settings",
                json={"workspace_id": "ws-123"},
                headers={"X-Persona-ID": "test-persona"}
            )
            assert resp.status_code == 400
            data = resp.json()
            assert "error" in data
            assert data["error"]["code"] == "missing_fields"

    def test_save_token_missing_api_token(self):
        mock_client, mock_db, mock_collection, _, _ = _make_mock_mongodb()
        with patch("clickup_mcp.storage.MongoClient", return_value=mock_client):
            settings = _make_settings()
            app = create_app(settings)
            client = TestClient(app)
            resp = client.post(
                "/token/settings",
                json={"api_token": "secret-token"},
                headers={"X-Persona-ID": "test-persona"}
            )
            assert resp.status_code == 400

    def test_save_token_invalid_body(self):
        mock_client, mock_db, mock_collection, _, _ = _make_mock_mongodb()
        with patch("clickup_mcp.storage.MongoClient", return_value=mock_client):
            settings = _make_settings()
            app = create_app(settings)
            client = TestClient(app)
            resp = client.post(
                "/token/settings",
                content=b"not json",
                headers={"X-Persona-ID": "test-persona"}
            )
            assert resp.status_code == 400


class TestTokenRemoval:
    def test_remove_single(self):
        mock_client, mock_db, mock_collection, _, _ = _make_mock_mongodb()
        with patch("clickup_mcp.storage.TokenStore.delete_token", new_callable=AsyncMock) as mock_del:
            mock_del.return_value = True
            with patch("clickup_mcp.storage.MongoClient", return_value=mock_client):
                settings = _make_settings()
                app = create_app(settings)
                client = TestClient(app)
                resp = client.request(
                    "DELETE",
                    "/token/settings",
                    json={"workspace_id": "ws-123"},
                    headers={"X-Persona-ID": "test-persona"}
                )
                assert resp.status_code == 200
                data = resp.json()
                assert data["status"] == "removed"

    def test_remove_not_found(self):
        mock_client, mock_db, mock_collection, _, _ = _make_mock_mongodb()
        with patch("clickup_mcp.storage.TokenStore.delete_token", new_callable=AsyncMock) as mock_del:
            mock_del.return_value = False
            with patch("clickup_mcp.storage.MongoClient", return_value=mock_client):
                settings = _make_settings()
                app = create_app(settings)
                client = TestClient(app)
                resp = client.request(
                    "DELETE",
                    "/token/settings",
                    json={"workspace_id": "ws-999"},
                    headers={"X-Persona-ID": "test-persona"}
                )
                assert resp.status_code == 200
                data = resp.json()
                assert data["status"] == "not_found"

    def test_remove_all(self):
        mock_client, mock_db, mock_collection, _, _ = _make_mock_mongodb()
        with patch("clickup_mcp.storage.TokenStore.get_all_tokens", new_callable=AsyncMock) as mock_all:
            mock_all.return_value = [
                {"workspace_id": "ws-1"},
                {"workspace_id": "ws-2"},
            ]
            with patch("clickup_mcp.storage.TokenStore.delete_token", new_callable=AsyncMock) as mock_del:
                mock_del.return_value = True
                with patch("clickup_mcp.storage.MongoClient", return_value=mock_client):
                    settings = _make_settings()
                    app = create_app(settings)
                    client = TestClient(app)
                    resp = client.delete(
                        "/token/settings",
                        headers={"X-Persona-ID": "test-persona"}
                    )
                    assert resp.status_code == 200
                    data = resp.json()
                    assert data["status"] == "removed"
                    assert data["workspaces_removed"] == 2
