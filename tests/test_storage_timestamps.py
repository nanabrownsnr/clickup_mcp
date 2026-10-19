from __future__ import annotations

import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

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


class TestTimestamps:
    """Tests for created_at and updated_at timestamp functionality."""

    async def test_save_token_sets_timestamps(self):
        """save_token should set created_at and updated_at to current time."""
        mock_client, mock_db, mock_collection, _, _ = _make_mock_mongodb()
        mock_collection.find_one = MagicMock(return_value=None)
        with patch("clickup_mcp.storage.MongoClient", return_value=mock_client):
            settings = _make_settings()
            store = TokenStore(settings)
            await store.save_token(
                persona_id="user-1",
                workspace_id="ws-123",
                encrypted_token={"encrypted_token": "abc", "salt": "def"},
            )
            call_args = mock_collection.replace_one.call_args
            doc = call_args[0][1]
            assert "created_at" in doc
            assert "updated_at" in doc
            assert doc["created_at"] is not None
            assert doc["updated_at"] is not None
            assert isinstance(doc["created_at"], datetime)
            assert isinstance(doc["updated_at"], datetime)

    async def test_save_token_preserves_existing_created_at(self):
        """save_token should preserve created_at if document already exists."""
        mock_client, mock_db, mock_collection, _, _ = _make_mock_mongodb()
        existing_created = datetime(2024, 1, 1, tzinfo=timezone.utc)
        mock_collection.find_one = MagicMock(return_value={
            "persona_id": "user-1",
            "workspace_id": "ws-123",
            "created_at": existing_created,
        })
        with patch("clickup_mcp.storage.MongoClient", return_value=mock_client):
            settings = _make_settings()
            store = TokenStore(settings)
            await store.save_token(
                persona_id="user-1",
                workspace_id="ws-123",
                encrypted_token={"encrypted_token": "abc", "salt": "def"},
            )
            call_args = mock_collection.replace_one.call_args
            doc = call_args[0][1]
            assert doc["created_at"] == existing_created
            assert doc["updated_at"] != existing_created

    async def test_save_oauth_token_sets_timestamps(self):
        """save_oauth_token should set created_at and updated_at."""
        mock_client, mock_db, mock_collection, mock_oauth, mock_session = _make_mock_mongodb()
        mock_oauth.find_one = MagicMock(return_value=None)
        with patch("clickup_mcp.storage.MongoClient", return_value=mock_client):
            settings = _make_settings()
            store = TokenStore(settings)
            await store.save_oauth_token(
                persona_id="user-1",
                workspace_id="ws-123",
                encrypted_access_token={"encrypted_token": "a", "salt": "s"},
                encrypted_refresh_token={"encrypted_token": "r", "salt": "s"},
                expires_at=3600,
            )
            call_args = mock_oauth.replace_one.call_args
            doc = call_args[0][1]
            assert "created_at" in doc
            assert "updated_at" in doc
            assert doc["created_at"] is not None
            assert doc["updated_at"] is not None

    async def test_save_session_sets_timestamp(self):
        """save_session should set created_at to current time."""
        mock_client, mock_db, mock_collection, mock_oauth, mock_session = _make_mock_mongodb()
        with patch("clickup_mcp.storage.MongoClient", return_value=mock_client):
            settings = _make_settings()
            store = TokenStore(settings)
            await store.save_session("state-123", {"persona_id": "user-1"})
            call_args = mock_session.replace_one.call_args
            doc = call_args[0][1]
            assert "created_at" in doc
            assert doc["created_at"] is not None
            assert isinstance(doc["created_at"], datetime)


class TestIndexConflictHandling:
    """Tests for MongoDB index creation conflict handling."""

    def test_index_skips_if_already_in_info(self):
        """If index exists in index_information(), skip creation."""
        mock_client, mock_db, mock_collection, mock_oauth, mock_session = _make_mock_mongodb()
        mock_collection.index_information = MagicMock(return_value={
            "persona_id_1": {"key": [("persona_id", 1)], "unique": True},
            "workspace_id_1": {"key": [("workspace_id", 1)]},
        })
        mock_oauth.index_information = MagicMock(return_value={
            "persona_id_1": {"key": [("persona_id", 1)]},
            "workspace_id_1": {"key": [("workspace_id", 1)]},
            "access_token_1": {"key": [("access_token", 1)], "sparse": True},
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
            mock_oauth.create_index.assert_not_called()
            mock_session.create_index.assert_not_called()

    def test_index_catches_code_85(self):
        """OperationFailure code 85 (IndexOptionsConflict) should be silently caught."""
        mock_client, mock_db, mock_collection, mock_oauth, mock_session = _make_mock_mongodb()
        mock_collection.index_information = MagicMock(return_value={})
        from pymongo.errors import OperationFailure
        failure = OperationFailure("Index conflict", 85)
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

    def test_index_catches_code_68(self):
        """OperationFailure code 68 (IndexNotFound) should be silently caught."""
        mock_client, mock_db, mock_collection, mock_oauth, mock_session = _make_mock_mongodb()
        mock_collection.index_information = MagicMock(return_value={})
        from pymongo.errors import OperationFailure
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

    def test_index_reraises_unknown_code(self):
        """Unknown OperationFailure codes should be re-raised."""
        mock_client, mock_db, mock_collection, mock_oauth, mock_session = _make_mock_mongodb()
        mock_collection.index_information = MagicMock(return_value={})
        from pymongo.errors import OperationFailure
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


class TestPersonaIndex:
    """Tests specifically for persona_id unique index."""

    def test_persona_id_unique_index_created(self):
        """persona_id unique index should be created on collections with unique=True."""
        mock_client, mock_db, mock_collection, _, _ = _make_mock_mongodb()
        with patch("clickup_mcp.storage.MongoClient", return_value=mock_client):
            settings = _make_settings()
            store = TokenStore(settings)
            # Trigger lazy initialization
            store._ensure_collection
            calls = mock_collection.create_index.call_args_list
            unique_calls = [c for c in calls if c[1].get("unique")]
            assert len(unique_calls) >= 1
            assert unique_calls[0][0][0] == "persona_id"

    def test_no_connection_on_init(self):
        """TokenStore.__init__ should not connect to MongoDB."""
        mock_client, _, _, _, _ = _make_mock_mongodb()
        with patch("clickup_mcp.storage.MongoClient", return_value=mock_client):
            settings = _make_settings()
            store = TokenStore(settings)
            # MongoClient should NOT be called during __init__
            assert store._client is None
            mock_collection = MagicMock()
            # The mock client's __getitem__ should not have been called
            assert not mock_client.__getitem__.called
