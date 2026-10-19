from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from pymongo.errors import OperationFailure

from clickup_mcp.config import Settings
from clickup_mcp.storage import TokenStore


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


class TestTokenStore:
    def test_init_no_connection(self):
        """TokenStore.__init__ should NOT connect to MongoDB (lazy connection)."""
        mock_client, _, _, _, _ = _make_mock_mongodb()
        with patch("clickup_mcp.storage.MongoClient", return_value=mock_client):
            settings = _make_settings()
            store = TokenStore(settings)
            # MongoClient should NOT be called during __init__
            mock_client.__getitem__.assert_not_called()
            assert store._client is None
            assert store._collection is None

    async def test_connection_triggered_on_first_operation(self):
        """MongoDB connection should be established on first database operation."""
        mock_client, mock_db, mock_collection, _, _ = _make_mock_mongodb()
        with patch("clickup_mcp.storage.MongoClient", return_value=mock_client):
            settings = _make_settings()
            store = TokenStore(settings)
            assert store._client is None
            await store.save_token(
                persona_id="user-1",
                workspace_id="ws-123",
                encrypted_token={"encrypted_token": "abc", "salt": "def"},
            )
            # After first operation, client should be initialized
            assert store._client is not None
            mock_collection.replace_one.assert_called_once()
            call_args = mock_collection.replace_one.call_args
            assert call_args[0][0] == {"persona_id": "user-1", "workspace_id": "ws-123"}

    async def test_save_token(self):
        mock_client, mock_db, mock_collection, _, _ = _make_mock_mongodb()
        with patch("clickup_mcp.storage.MongoClient", return_value=mock_client):
            settings = _make_settings()
            store = TokenStore(settings)
            await store.save_token(
                persona_id="user-1",
                workspace_id="ws-123",
                encrypted_token={"encrypted_token": "abc", "salt": "def"},
            )
            mock_collection.replace_one.assert_called_once()
            call_args = mock_collection.replace_one.call_args
            assert call_args[0][0] == {"persona_id": "user-1", "workspace_id": "ws-123"}

    async def test_get_token_found(self):
        mock_client, mock_db, mock_collection, _, _ = _make_mock_mongodb()
        mock_collection.find_one = MagicMock(return_value={
            "persona_id": "user-1",
            "workspace_id": "ws-123",
            "encrypted_token": {"encrypted_token": "abc", "salt": "def"},
        })
        with patch("clickup_mcp.storage.MongoClient", return_value=mock_client):
            settings = _make_settings()
            store = TokenStore(settings)
            result = await store.get_token("user-1", "ws-123")
            assert result is not None
            assert result["workspace_id"] == "ws-123"

    async def test_get_token_not_found(self):
        mock_client, mock_db, mock_collection, _, _ = _make_mock_mongodb()
        mock_collection.find_one = MagicMock(return_value=None)
        with patch("clickup_mcp.storage.MongoClient", return_value=mock_client):
            settings = _make_settings()
            store = TokenStore(settings)
            result = await store.get_token("user-1", "ws-999")
            assert result is None

    async def test_get_all_tokens(self):
        mock_client, mock_db, mock_collection, _, _ = _make_mock_mongodb()
        mock_collection.find = MagicMock(return_value=[
            {"workspace_id": "ws-1"},
            {"workspace_id": "ws-2"},
        ])
        with patch("clickup_mcp.storage.MongoClient", return_value=mock_client):
            settings = _make_settings()
            store = TokenStore(settings)
            result = await store.get_all_tokens("user-1")
            assert len(result) == 2
            assert result[0]["workspace_id"] == "ws-1"

    async def test_delete_token(self):
        mock_client, mock_db, mock_collection, _, _ = _make_mock_mongodb()
        mock_collection.delete_one = MagicMock(return_value=MagicMock(deleted_count=1))
        with patch("clickup_mcp.storage.MongoClient", return_value=mock_client):
            settings = _make_settings()
            store = TokenStore(settings)
            result = await store.delete_token("user-1", "ws-123")
            assert result is True

    async def test_delete_token_not_found(self):
        mock_client, mock_db, mock_collection, _, _ = _make_mock_mongodb()
        mock_collection.delete_one = MagicMock(return_value=MagicMock(deleted_count=0))
        with patch("clickup_mcp.storage.MongoClient", return_value=mock_client):
            settings = _make_settings()
            store = TokenStore(settings)
            result = await store.delete_token("user-1", "ws-999")
            assert result is False

    async def test_list_workspaces(self):
        mock_client, mock_db, mock_collection, _, _ = _make_mock_mongodb()
        mock_collection.distinct = MagicMock(return_value=["ws-1", "ws-2"])
        with patch("clickup_mcp.storage.MongoClient", return_value=mock_client):
            settings = _make_settings()
            store = TokenStore(settings)
            result = await store.list_workspaces("user-1")
            assert result == ["ws-1", "ws-2"]

    def test_index_creation_skips_if_already_exists(self):
        """Index should not be created if index_information() returns it."""
        mock_client, mock_db, mock_collection, mock_oauth, mock_session = _make_mock_mongodb()
        mock_collection.index_information = MagicMock(return_value={
            "persona_id_1": {"key": [("persona_id", 1)], "unique": True},
            "workspace_id_1": {"key": [("workspace_id", 1)]},
        })
        mock_oauth.index_information = MagicMock(return_value={
            "persona_id_1": {"key": [("persona_id", 1)]},
        })
        mock_session.index_information = MagicMock(return_value={
            "state_1": {"key": [("state", 1)], "unique": True},
        })
        with patch("clickup_mcp.storage.MongoClient", return_value=mock_client):
            settings = _make_settings()
            store = TokenStore(settings)
            # Trigger lazy initialization
            store._ensure_collection
            mock_collection.create_index.assert_not_called()

    def test_index_creation_with_if_not_exists_code_85(self):
        """OperationFailure code 85 (IndexOptionsConflict) should be caught and skipped."""
        mock_client, mock_db, mock_collection, mock_oauth, mock_session = _make_mock_mongodb()
        mock_collection.index_information = MagicMock(return_value={})
        failure = OperationFailure("Index with name already exists", 85)
        mock_collection.create_index = MagicMock(side_effect=failure)
        mock_oauth.index_information = MagicMock(return_value={})
        mock_oauth.create_index = MagicMock()
        mock_session.index_information = MagicMock(return_value={})
        mock_session.create_index = MagicMock()
        with patch("clickup_mcp.storage.MongoClient", return_value=mock_client):
            settings = _make_settings()
            store = TokenStore(settings)
            # Trigger lazy initialization
            store._ensure_collection
            mock_oauth.create_index.assert_called()
            mock_session.create_index.assert_called()

    def test_index_creation_with_if_not_exists_code_68(self):
        """OperationFailure code 68 (IndexNotFound) should be caught and skipped."""
        mock_client, mock_db, mock_collection, mock_oauth, mock_session = _make_mock_mongodb()
        mock_collection.index_information = MagicMock(return_value={})
        failure = OperationFailure("Index not found", 68)
        mock_collection.create_index = MagicMock(side_effect=failure)
        mock_oauth.index_information = MagicMock(return_value={})
        mock_oauth.create_index = MagicMock()
        mock_session.index_information = MagicMock(return_value={})
        mock_session.create_index = MagicMock()
        with patch("clickup_mcp.storage.MongoClient", return_value=mock_client):
            settings = _make_settings()
            store = TokenStore(settings)
            # Trigger lazy initialization
            store._ensure_collection
            mock_oauth.create_index.assert_called()
            mock_session.create_index.assert_called()

    def test_index_creation_raises_unknown_error(self):
        """Unknown OperationFailure codes should be re-raised."""
        mock_client, mock_db, mock_collection, mock_oauth, mock_session = _make_mock_mongodb()
        mock_collection.index_information = MagicMock(return_value={})
        failure = OperationFailure("Unknown error", 99)
        mock_collection.create_index = MagicMock(side_effect=failure)
        mock_oauth.index_information = MagicMock(return_value={})
        mock_oauth.create_index = MagicMock()
        mock_session.index_information = MagicMock(return_value={})
        mock_session.create_index = MagicMock()
        with patch("clickup_mcp.storage.MongoClient", return_value=mock_client):
            settings = _make_settings()
            store = TokenStore(settings)
            with pytest.raises(OperationFailure, match="Unknown error"):
                store._ensure_collection

    def test_client_property_returns_none_before_connection(self):
        """client property should return None before any database operation."""
        mock_client, _, _, _, _ = _make_mock_mongodb()
        with patch("clickup_mcp.storage.MongoClient", return_value=mock_client):
            settings = _make_settings()
            store = TokenStore(settings)
            assert store.client is None

    def test_client_property_returns_client_after_connection(self):
        """client property should return MongoClient after first operation."""
        mock_client, mock_db, mock_collection, _, _ = _make_mock_mongodb()
        with patch("clickup_mcp.storage.MongoClient", return_value=mock_client):
            settings = _make_settings()
            store = TokenStore(settings)
            assert store.client is None
            mock_collection.find_one = MagicMock(return_value=None)
            # Trigger connection
            store._ensure_collection
            assert store.client is mock_client
