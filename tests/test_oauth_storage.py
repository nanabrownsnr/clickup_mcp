from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from clickup_mcp.config import Settings
from clickup_mcp.storage import TokenStore
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
    return mock_client, mock_db, mock_collection, mock_oauth_collection, mock_session_collection


class TestOAuth2TokenStorage:
    async def test_save_oauth_token(self):
        mock_client, mock_db, mock_collection, mock_oauth, mock_session = _make_mock_mongodb()
        with patch("clickup_mcp.storage.MongoClient", return_value=mock_client):
            settings = _make_settings()
            store = TokenStore(settings)

            access_enc = encrypt_token("access-token", "l2G_gvqENw5Xdptya18vB8IyK7yEbZiLI4PtCP-6lGE", "user:ws")
            refresh_enc = encrypt_token("refresh-token", "l2G_gvqENw5Xdptya18vB8IyK7yEbZiLI4PtCP-6lGE", "user:ws")

            await store.save_oauth_token(
                persona_id="user-1",
                workspace_id="ws-123",
                encrypted_access_token=access_enc,
                encrypted_refresh_token=refresh_enc,
                expires_at=3600,
            )

            mock_oauth.replace_one.assert_called_once()
            call_args = mock_oauth.replace_one.call_args
            assert call_args[0][0] == {"persona_id": "user-1", "workspace_id": "ws-123"}

    async def test_get_oauth_token_found(self):
        mock_client, mock_db, mock_collection, mock_oauth, mock_session = _make_mock_mongodb()
        mock_oauth.find_one = MagicMock(return_value={
            "persona_id": "user-1",
            "workspace_id": "ws-123",
            "encrypted_access_token": {"encrypted_token": "abc", "salt": "def"},
            "encrypted_refresh_token": {"encrypted_token": "xyz", "salt": "ghi"},
            "expires_at": 3600,
        })
        with patch("clickup_mcp.storage.MongoClient", return_value=mock_client):
            settings = _make_settings()
            store = TokenStore(settings)
            result = await store.get_oauth_token("user-1", "ws-123")
            assert result is not None
            assert result["workspace_id"] == "ws-123"

    async def test_get_oauth_token_not_found(self):
        mock_client, mock_db, mock_collection, mock_oauth, mock_session = _make_mock_mongodb()
        mock_oauth.find_one = MagicMock(return_value=None)
        with patch("clickup_mcp.storage.MongoClient", return_value=mock_client):
            settings = _make_settings()
            store = TokenStore(settings)
            result = await store.get_oauth_token("user-1", "ws-999")
            assert result is None

    async def test_get_oauth_tokens_by_persona(self):
        mock_client, mock_db, mock_collection, mock_oauth, mock_session = _make_mock_mongodb()
        mock_oauth.find = MagicMock(return_value=[
            {"workspace_id": "ws-1"},
            {"workspace_id": "ws-2"},
        ])
        with patch("clickup_mcp.storage.MongoClient", return_value=mock_client):
            settings = _make_settings()
            store = TokenStore(settings)
            result = await store.get_oauth_tokens_by_persona("user-1")
            assert len(result) == 2

    async def test_delete_oauth_token(self):
        mock_client, mock_db, mock_collection, mock_oauth, mock_session = _make_mock_mongodb()
        mock_oauth.delete_one = MagicMock(return_value=MagicMock(deleted_count=1))
        with patch("clickup_mcp.storage.MongoClient", return_value=mock_client):
            settings = _make_settings()
            store = TokenStore(settings)
            result = await store.delete_oauth_token("user-1", "ws-123")
            assert result is True

    async def test_delete_all_oauth_tokens(self):
        mock_client, mock_db, mock_collection, mock_oauth, mock_session = _make_mock_mongodb()
        mock_oauth.delete_many = MagicMock(return_value=MagicMock(deleted_count=3))
        with patch("clickup_mcp.storage.MongoClient", return_value=mock_client):
            settings = _make_settings()
            store = TokenStore(settings)
            result = await store.delete_all_oauth_tokens("user-1")
            assert result == 3

    async def test_list_oauth_workspaces(self):
        mock_client, mock_db, mock_collection, mock_oauth, mock_session = _make_mock_mongodb()
        mock_oauth.distinct = MagicMock(return_value=["ws-1", "ws-2", "ws-3"])
        with patch("clickup_mcp.storage.MongoClient", return_value=mock_client):
            settings = _make_settings()
            store = TokenStore(settings)
            result = await store.list_oauth_workspaces("user-1")
            assert result == ["ws-1", "ws-2", "ws-3"]


class TestOAuth2SessionStorage:
    async def test_save_session(self):
        mock_client, mock_db, mock_collection, mock_oauth, mock_session = _make_mock_mongodb()
        with patch("clickup_mcp.storage.MongoClient", return_value=mock_client):
            settings = _make_settings()
            store = TokenStore(settings)

            await store.save_session("state-123", {
                "persona_id": "user-1",
                "workspace_id": "ws-123",
            })

            mock_session.replace_one.assert_called_once()

    async def test_get_session_found(self):
        mock_client, mock_db, mock_collection, mock_oauth, mock_session = _make_mock_mongodb()
        mock_session.find_one = MagicMock(return_value={
            "state": "state-123",
            "session_data": {"persona_id": "user-1", "workspace_id": "ws-123"},
        })
        with patch("clickup_mcp.storage.MongoClient", return_value=mock_client):
            settings = _make_settings()
            store = TokenStore(settings)
            result = await store.get_session("state-123")
            assert result is not None
            assert result["session_data"]["persona_id"] == "user-1"

    async def test_get_session_not_found(self):
        mock_client, mock_db, mock_collection, mock_oauth, mock_session = _make_mock_mongodb()
        mock_session.find_one = MagicMock(return_value=None)
        with patch("clickup_mcp.storage.MongoClient", return_value=mock_client):
            settings = _make_settings()
            store = TokenStore(settings)
            result = await store.get_session("invalid-state")
            assert result is None

    async def test_delete_session(self):
        mock_client, mock_db, mock_collection, mock_oauth, mock_session = _make_mock_mongodb()
        mock_session.delete_one = MagicMock(return_value=MagicMock(deleted_count=1))
        with patch("clickup_mcp.storage.MongoClient", return_value=mock_client):
            settings = _make_settings()
            store = TokenStore(settings)
            result = await store.delete_session("state-123")
            assert result is True

    async def test_delete_session_not_found(self):
        mock_client, mock_db, mock_collection, mock_oauth, mock_session = _make_mock_mongodb()
        mock_session.delete_one = MagicMock(return_value=MagicMock(deleted_count=0))
        with patch("clickup_mcp.storage.MongoClient", return_value=mock_client):
            settings = _make_settings()
            store = TokenStore(settings)
            result = await store.delete_session("invalid-state")
            assert result is False
