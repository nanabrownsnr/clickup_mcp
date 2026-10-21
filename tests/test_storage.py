"""Tests for MongoDB token store."""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from clickup_mcp.config import Settings
from clickup_mcp.storage import TokenStore, get_active_store, set_active_store


def _make_settings(**overrides):
    base = {
        "CLICKUP_API_TOKEN": "test-api-token",
        "ENCRYPTION_KEY": "l2G_gvqENw5Xdptya18vB8IyK7yEbZiLI4PtCP-6lGE",
        "MONGODB_URI": "mongodb://localhost:27017",
    }
    base.update(overrides)
    return Settings(**base)


def _mock_db(collection):
    mock_db = MagicMock()
    mock_db.__getitem__ = MagicMock(side_effect=lambda key: {
        "api_tokens": collection,
        "oauth_tokens": MagicMock(),
        "oauth_sessions": MagicMock(),
    }.get(key, MagicMock()))
    return mock_db


def _mock_collection():
    c = MagicMock()
    c.find_one = AsyncMock(return_value=None)
    c.replace_one = AsyncMock(return_value=MagicMock(upserted_id="x"))
    c.delete_one = AsyncMock(return_value=MagicMock(deleted_count=1))
    c.index_information = MagicMock(return_value={})
    return c


class TestTokenStore:
    def test_init_no_connection(self):
        with patch("clickup_mcp.storage.AsyncMongoClient") as mock:
            mock.return_value = MagicMock()
            settings = _make_settings()
            store = TokenStore(settings)
            assert store._client is None

    async def test_connection_on_first_operation(self):
        collection = _mock_collection()
        mock_client = MagicMock()
        mock_client.__getitem__ = MagicMock(return_value=_mock_db(collection))
        with patch("clickup_mcp.storage.AsyncMongoClient", return_value=mock_client):
            settings = _make_settings()
            store = TokenStore(settings)
            assert store._client is None
            await store.save_token("u1", "p1", "ws-123", {"encrypted_token": "abc"})
            assert store._client is not None
            collection.replace_one.assert_called_once()

    async def test_get_token_found(self):
        collection = _mock_collection()
        collection.find_one = AsyncMock(return_value={"workspace_id": "ws-123"})
        mock_client = MagicMock()
        mock_client.__getitem__ = MagicMock(return_value=_mock_db(collection))
        with patch("clickup_mcp.storage.AsyncMongoClient", return_value=mock_client):
            settings = _make_settings()
            store = TokenStore(settings)
            result = await store.get_token("u1", "p1", "ws-123")
            assert result is not None
            assert result["workspace_id"] == "ws-123"

    async def test_get_token_not_found(self):
        collection = _mock_collection()
        mock_client = MagicMock()
        mock_client.__getitem__ = MagicMock(return_value=_mock_db(collection))
        with patch("clickup_mcp.storage.AsyncMongoClient", return_value=mock_client):
            settings = _make_settings()
            store = TokenStore(settings)
            result = await store.get_token("u1", "p1", "ws-999")
            assert result is None

    async def test_delete_token_found(self):
        collection = _mock_collection()
        collection.delete_one = AsyncMock(return_value=MagicMock(deleted_count=1))
        mock_client = MagicMock()
        mock_client.__getitem__ = MagicMock(return_value=_mock_db(collection))
        with patch("clickup_mcp.storage.AsyncMongoClient", return_value=mock_client):
            settings = _make_settings()
            store = TokenStore(settings)
            result = await store.delete_token("u1", "p1", "ws-123")
            assert result is True

    async def test_delete_token_not_found(self):
        collection = _mock_collection()
        collection.delete_one = AsyncMock(return_value=MagicMock(deleted_count=0))
        mock_client = MagicMock()
        mock_client.__getitem__ = MagicMock(return_value=_mock_db(collection))
        with patch("clickup_mcp.storage.AsyncMongoClient", return_value=mock_client):
            settings = _make_settings()
            store = TokenStore(settings)
            result = await store.delete_token("u1", "p1", "ws-999")
            assert result is False

    def test_active_store_get_set(self):
        assert get_active_store() is None
        settings = _make_settings()
        store = TokenStore(settings)
        set_active_store(store)
        assert get_active_store() is store
        set_active_store(None)
        assert get_active_store() is None
