"""Test fixtures for clickup_mcp."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from clickup_mcp.config import Settings
from clickup_mcp.storage import set_active_store, TokenStore


# Valid URL-safe base64 encoded keys for tests
_TEST_KEY_32 = "l2G_gvqENw5Xdptya18vB8IyK7yEbZiLI4PtCP-6lGE"
_TEST_KEY_16 = "me8oIy6lGBctWAPHudSKJg"
_TEST_KEY_24 = "EhIRdKph9hjomdCAWML_IQr_euKo5TP1"


def _make_settings(**overrides):
    base = {
        "CLICKUP_API_TOKEN": "test-api-token",
        "ENCRYPTION_KEY": _TEST_KEY_32,
        "MONGODB_URI": "mongodb://localhost:27017",
    }
    base.update(overrides)
    return Settings(**base)


@pytest.fixture
def test_encryption_key_32():
    return _TEST_KEY_32


@pytest.fixture
def test_encryption_key_16():
    return _TEST_KEY_16


@pytest.fixture
def test_encryption_key_24():
    return _TEST_KEY_24


@pytest.fixture
def mock_mongodb():
    """Mock AsyncMongoClient for tests that need it."""
    from pymongo import AsyncMongoClient

    with patch("clickup_mcp.storage.AsyncMongoClient") as mock:
        mock_client_instance = MagicMock()
        mock_db = MagicMock()
        mock_collection = MagicMock()
        mock_oauth_collection = MagicMock()
        mock_session_collection = MagicMock()

        def getitem(key):
            return {
                "api_tokens": mock_collection,
                "oauth_tokens": mock_oauth_collection,
                "oauth_sessions": mock_session_collection,
            }.get(key, MagicMock())

        mock_db.__getitem__ = MagicMock(side_effect=getitem)
        mock_collection.find_one = AsyncMock(return_value=None)
        mock_collection.find = AsyncMock(return_value=MagicMock(to_list=AsyncMock(return_value=[])))
        mock_collection.replace_one = AsyncMock(return_value=MagicMock(upserted_id="x"))
        mock_collection.delete_one = AsyncMock(return_value=MagicMock(deleted_count=1))
        mock_collection.delete_many = AsyncMock(return_value=MagicMock(deleted_count=1))
        mock_collection.distinct = AsyncMock(return_value=[])
        mock_collection.create_index = AsyncMock()
        mock_collection.index_information = MagicMock(return_value={})
        mock_oauth_collection.find_one = AsyncMock(return_value=None)
        mock_oauth_collection.find = AsyncMock(return_value=MagicMock(to_list=AsyncMock(return_value=[])))
        mock_oauth_collection.replace_one = AsyncMock(return_value=MagicMock(upserted_id="x"))
        mock_oauth_collection.delete_one = AsyncMock(return_value=MagicMock(deleted_count=1))
        mock_oauth_collection.delete_many = AsyncMock(return_value=MagicMock(deleted_count=1))
        mock_oauth_collection.distinct = AsyncMock(return_value=[])
        mock_oauth_collection.create_index = AsyncMock()
        mock_oauth_collection.index_information = MagicMock(return_value={})
        mock_session_collection.find_one = AsyncMock(return_value=None)
        mock_session_collection.replace_one = AsyncMock(return_value=MagicMock(upserted_id="x"))
        mock_session_collection.delete_one = AsyncMock(return_value=MagicMock(deleted_count=1))
        mock_session_collection.create_index = AsyncMock()
        mock_session_collection.index_information = MagicMock(return_value={})

        mock_db.__getitem__ = MagicMock(side_effect=getitem)
        mock_client_instance.__getitem__ = MagicMock(return_value=mock_db)
        mock.return_value = mock_client_instance
        yield mock, mock_collection, mock_oauth_collection


@pytest.fixture
async def active_store(mock_mongodb):
    """Set up an active TokenStore for tests."""
    _, _, _ = mock_mongodb
    settings = _make_settings()
    store = TokenStore(settings)
    set_active_store(store)
    yield store
    set_active_store(None)


@pytest.fixture
def app_client():
    """Create a TestClient for the MCP app with mocked MongoDB."""
    with patch("clickup_mcp.storage.AsyncMongoClient"):
        from clickup_mcp.main import mcp
        from starlette.testclient import TestClient
        client = TestClient(mcp.http_app())
        yield client
