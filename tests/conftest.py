from __future__ import annotations

import pytest


# Valid URL-safe base64 encoded keys for tests
_TEST_KEY_32 = "l2G_gvqENw5Xdptya18vB8IyK7yEbZiLI4PtCP-6lGE"
_TEST_KEY_16 = "me8oIy6lGBctWAPHudSKJg"
_TEST_KEY_24 = "EhIRdKph9hjomdCAWML_IQr_euKo5TP1"


@pytest.fixture
def mock_mongodb():
    """Mock MongoDB connection for tests that need it."""
    from unittest.mock import MagicMock, patch
    with patch("clickup_mcp.storage.MongoClient") as mock:
        mock_client_instance = MagicMock()
        mock_db = MagicMock()
        mock_collection = MagicMock()
        mock_oauth_collection = MagicMock()
        mock_session_collection = MagicMock()

        mock_db.__getitem__ = MagicMock(side_effect=lambda key: {
            "api_tokens": mock_collection,
            "oauth_tokens": mock_oauth_collection,
            "oauth_sessions": mock_session_collection,
        }.get(key, MagicMock()))

        mock_client_instance.__getitem__ = MagicMock(return_value=mock_db)
        mock_collection.create_index = MagicMock()
        mock_oauth_collection.create_index = MagicMock()
        mock_session_collection.create_index = MagicMock()

        mock.return_value = mock_client_instance
        yield mock, mock_collection


@pytest.fixture
def test_encryption_key_32():
    """Return a valid URL-safe base64 encoded 32-byte encryption key."""
    return _TEST_KEY_32


@pytest.fixture
def test_encryption_key_16():
    """Return a valid URL-safe base64 encoded 16-byte encryption key."""
    return _TEST_KEY_16


@pytest.fixture
def test_encryption_key_24():
    """Return a valid URL-safe base64 encoded 24-byte encryption key."""
    return _TEST_KEY_24
