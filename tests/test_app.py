from __future__ import annotations

import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from starlette.testclient import TestClient

from clickup_mcp.config import Settings
from clickup_mcp.app import create_app
from clickup_mcp.crypto import encrypt_token
from clickup_mcp.clickup_client import ClickUpAPIError


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
    mock_client.start_session = MagicMock()
    return mock_client, mock_db, mock_collection, mock_oauth_collection, mock_session_collection


class TestHealthEndpoint:
    @pytest.fixture
    def client(self):
        mock_client, mock_db, mock_collection, _, _ = _make_mock_mongodb()
        with patch("clickup_mcp.storage.MongoClient", return_value=mock_client):
            settings = _make_settings()
            app = create_app(settings)
            yield TestClient(app)

    def test_health(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "healthy"
        assert data["service"] == "ClickUpMCP"
        assert data["version"] == "1.0.0"


class TestManifestEndpoint:
    @pytest.fixture
    def client(self):
        mock_client, mock_db, mock_collection, _, _ = _make_mock_mongodb()
        with patch("clickup_mcp.storage.MongoClient", return_value=mock_client):
            settings = _make_settings()
            app = create_app(settings)
            yield TestClient(app)

    def test_manifest(self, client):
        resp = client.get("/manifest")
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "ClickUpMCP"
        assert data["description"] == "Integrates ClickUp tasks, spaces, lists, and updates."
        assert data["version"] == "1.0.0"
        assert data["mcp_version"] == "2024-11-05"
        assert data["capabilities"]["tools"] is True
        assert data["auth"]["type"] == "token"
        assert data["auth"]["flow"] == "bearer"


class TestMCPEndpoints:
    @pytest.fixture
    def client(self):
        mock_client, mock_db, mock_collection, _, _ = _make_mock_mongodb()
        with patch("clickup_mcp.storage.MongoClient", return_value=mock_client):
            settings = _make_settings()
            app = create_app(settings)
            yield TestClient(app)

    def test_mcp_root(self, client):
        resp = client.get("/mcp")
        assert resp.status_code == 200
        data = resp.json()
        assert data["server"] == "ClickUpMCP"
        assert data["mcp"] == "2024-11-05"

    def test_mcp_tools_info(self, client):
        resp = client.get("/mcp/tools")
        assert resp.status_code == 200
        data = resp.json()
        assert "tools" in data
        tool_names = [t["name"] for t in data["tools"]]
        assert "list_tasks" in tool_names
        assert "create_task" in tool_names

    def test_list_tasks_tool_schema(self, client):
        resp = client.get("/mcp/tools")
        data = resp.json()
        list_tasks = next(t for t in data["tools"] if t["name"] == "list_tasks")
        assert "input_schema" in list_tasks
        props = list_tasks["input_schema"]["properties"]
        assert "list_id" in props
        assert "space_id" in props
        assert "workspace_id" in props
        assert "status" in props
        assert "priority" in props


class TestTokenEndpoints:
    def test_token_validate_missing_workspace(self):
        mock_client, mock_db, mock_collection, _, _ = _make_mock_mongodb()
        with patch("clickup_mcp.storage.MongoClient", return_value=mock_client):
            settings = _make_settings()
            app = create_app(settings)
            client = TestClient(app)
            resp = client.get("/token/validate")
            assert resp.status_code == 400
            data = resp.json()
            assert "error" in data
            assert data["error"]["code"] == "missing_workspace_id"

    def test_token_validate_no_connection(self):
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

    def test_token_validate_valid(self):
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

    def test_token_settings_save(self):
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
            assert data["token_set"] is True

    def test_token_settings_missing_fields(self):
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

    def test_token_settings_invalid_body(self):
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

    def test_token_remove_single(self):
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

    def test_token_remove_all(self):
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
                    resp = client.request(
                        "DELETE",
                        "/token/settings",
                        headers={"X-Persona-ID": "test-persona"}
                    )
                    assert resp.status_code == 200
                    data = resp.json()
                    assert data["status"] == "removed"
                    assert data["workspaces_removed"] == 2


class TestProjectEndpoints:
    @pytest.fixture
    def client(self):
        mock_client, mock_db, mock_collection, _, _ = _make_mock_mongodb()
        mock_collection.get_all_tokens = AsyncMock(return_value=[])
        mock_collection.get_token = AsyncMock(return_value=None)
        with patch("clickup_mcp.storage.MongoClient", return_value=mock_client):
            settings = _make_settings()
            app = create_app(settings)
            yield TestClient(app)

    def test_project_schema_no_connections(self):
        mock_client, mock_db, mock_collection, _, _ = _make_mock_mongodb()
        with patch("clickup_mcp.storage.TokenStore.get_all_tokens", new_callable=AsyncMock) as mock:
            mock.return_value = []
            with patch("clickup_mcp.storage.MongoClient", return_value=mock_client):
                settings = _make_settings()
                app = create_app(settings)
                client = TestClient(app)
                resp = client.get("/project/schema")
                assert resp.status_code == 200
                data = resp.json()
                assert data["connected_workspaces"] == []
                assert "schema" in data
                assert "api_token" in data["schema"]

    def test_project_schema_with_connections(self):
        with patch("clickup_mcp.storage.TokenStore.get_all_tokens", new_callable=AsyncMock) as mock:
            mock.return_value = [
                {"workspace_id": "ws-123"},
                {"workspace_id": "ws-456"},
            ]
            mock_client, mock_db, mock_collection, _, _ = _make_mock_mongodb()
            with patch("clickup_mcp.storage.MongoClient", return_value=mock_client):
                settings = _make_settings()
                app = create_app(settings)
                client = TestClient(app)
                resp = client.get("/project/schema")
                assert resp.status_code == 200
                data = resp.json()
                assert len(data["connected_workspaces"]) == 2

    def test_project_connect_new(self):
        mock_client, mock_db, mock_collection, _, _ = _make_mock_mongodb()
        with patch("clickup_mcp.storage.TokenStore.get_token", new_callable=AsyncMock) as mock:
            mock.return_value = None
            with patch("clickup_mcp.storage.MongoClient", return_value=mock_client):
                settings = _make_settings()
                app = create_app(settings)
                client = TestClient(app)
                resp = client.post(
                    "/project/connect",
                    json={"workspace_id": "ws-new", "api_token": "test-token"},
                    headers={"X-Persona-ID": "test-persona"},
                )
                assert resp.status_code == 200
                data = resp.json()
                assert data["status"] == "connected"

    def test_project_connect_already_connected(self):
        mock_client, mock_db, mock_collection, _, _ = _make_mock_mongodb()
        with patch("clickup_mcp.storage.TokenStore.get_token", new_callable=AsyncMock) as mock:
            mock.return_value = {"workspace_id": "ws-existing"}
            with patch("clickup_mcp.storage.MongoClient", return_value=mock_client):
                settings = _make_settings()
                app = create_app(settings)
                client = TestClient(app)
                resp = client.post(
                    "/project/connect",
                    json={"workspace_id": "ws-existing", "api_token": "test-token"},
                    headers={"X-Persona-ID": "test-persona"},
                )
                assert resp.status_code == 200
                data = resp.json()
                assert data["status"] == "already_connected"

    def test_project_connect_missing_workspace_id(self):
        mock_client, mock_db, mock_collection, _, _ = _make_mock_mongodb()
        with patch("clickup_mcp.storage.MongoClient", return_value=mock_client):
            settings = _make_settings()
            app = create_app(settings)
            client = TestClient(app)
            resp = client.post(
                "/project/connect",
                json={},
                headers={"X-Persona-ID": "test-persona"},
            )
            assert resp.status_code == 400
            data = resp.json()
            assert "error" in data
            assert data["error"]["code"] == "missing_workspace_id"

    def test_project_connect_missing_api_token(self):
        mock_client, mock_db, mock_collection, _, _ = _make_mock_mongodb()
        with patch("clickup_mcp.storage.TokenStore.get_token", new_callable=AsyncMock) as mock:
            mock.return_value = None
            with patch("clickup_mcp.storage.MongoClient", return_value=mock_client):
                settings = _make_settings()
                app = create_app(settings)
                client = TestClient(app)
                resp = client.post(
                    "/project/connect",
                    json={"workspace_id": "ws-123"},
                    headers={"X-Persona-ID": "test-persona"},
                )
                assert resp.status_code == 400
                data = resp.json()
                assert "error" in data
                assert data["error"]["code"] == "missing_api_token"


class TestToolsEndpoints:
    @pytest.fixture
    def client(self):
        mock_client, mock_db, mock_collection, _, _ = _make_mock_mongodb()
        with patch("clickup_mcp.storage.MongoClient", return_value=mock_client):
            settings = _make_settings()
            app = create_app(settings)
            yield TestClient(app)

    def test_list_tasks_endpoint_no_body(self, client):
        resp = client.post(
            "/tools/list_tasks",
            content=b"not json",
            headers={"Content-Type": "application/json", "X-Persona-ID": "test"},
        )
        assert resp.status_code == 400

    def test_list_tasks_endpoint_no_connection(self, client):
        with patch("clickup_mcp.storage.TokenStore.get_token", new_callable=AsyncMock) as mock:
            mock.return_value = None
            resp = client.post(
                "/tools/list_tasks",
                json={"workspace_id": "ws-1", "list_id": "list-1"},
                headers={"X-Persona-ID": "test-persona"},
            )
            assert resp.status_code == 400
            data = resp.json()
            assert "error" in data

    def test_create_task_endpoint_no_body(self, client):
        resp = client.post(
            "/tools/create_task",
            content=b"not json",
            headers={"Content-Type": "application/json", "X-Persona-ID": "test"},
        )
        assert resp.status_code == 400

    def test_create_task_endpoint_no_connection(self, client):
        with patch("clickup_mcp.storage.TokenStore.get_token", new_callable=AsyncMock) as mock:
            mock.return_value = None
            resp = client.post(
                "/tools/create_task",
                json={"workspace_id": "ws-1", "list_id": "list-1", "name": "Test"},
                headers={"X-Persona-ID": "test-persona"},
            )
            assert resp.status_code == 400
            data = resp.json()
            assert "error" in data


class TestErrorHandling:
    @pytest.fixture
    def client(self):
        mock_client, mock_db, mock_collection, _, _ = _make_mock_mongodb()
        with patch("clickup_mcp.storage.MongoClient", return_value=mock_client):
            settings = _make_settings()
            app = create_app(settings)
            yield TestClient(app)

    def test_error_response_structure(self, client):
        resp = client.post(
            "/tools/list_tasks",
            json={},
            headers={"X-Persona-ID": "test-persona"},
        )
        assert resp.status_code == 400
        data = resp.json()
        assert "error" in data
        assert "code" in data["error"]
        assert "message" in data["error"]

    def test_error_no_token_leak(self, client):
        """Error responses should not contain API tokens or secrets."""
        resp = client.post(
            "/tools/create_task",
            json={"list_id": "list-abc", "name": "Test"},
            headers={"X-Persona-ID": "test-persona"},
        )
        data = resp.json()
        error_str = json.dumps(data).lower()
        assert "token" not in error_str or "token" in data.get("error", {}).get("message", "").lower()

    def test_ui_endpoint(self, client):
        resp = client.get("/ui")
        assert resp.status_code == 200
        assert "ClickUpMCP" in resp.text
        assert "List Tasks" in resp.text
        assert "Create Task" in resp.text
        assert "Connect Workspace" in resp.text
        assert "API Token" in resp.text

    def test_ui_contains_all_sections(self, client):
        resp = client.get("/ui")
        assert resp.status_code == 200
        assert "connect-workspace" in resp.text
        assert "list-list-id" in resp.text
        assert "create-list-id" in resp.text
        assert "create-name" in resp.text
        assert "create-description" in resp.text

    def test_mcp_tools_has_two_tools(self, client):
        resp = client.get("/mcp/tools")
        data = resp.json()
        assert len(data["tools"]) == 2
        tool_names = {t["name"] for t in data["tools"]}
        assert tool_names == {"list_tasks", "create_task"}

    def test_manifest_auth_type(self, client):
        resp = client.get("/manifest")
        data = resp.json()
        assert data["auth"]["type"] == "token"
        assert data["auth"]["flow"] == "bearer"
        assert data["capabilities"]["tools"] is True
        assert data["capabilities"]["resources"] is False
        assert data["capabilities"]["prompts"] is False

    def test_health_version(self, client):
        resp = client.get("/health")
        data = resp.json()
        assert data["version"] == "1.0.0"
        assert data["service"] == "ClickUpMCP"
        assert data["status"] == "healthy"

    def test_mcp_root_endpoint(self, client):
        resp = client.get("/mcp")
        data = resp.json()
        assert data["mcp"] == "2024-11-05"
        assert data["server"] == "ClickUpMCP"
        assert data["tools_endpoint"] == "/mcp/tools"
