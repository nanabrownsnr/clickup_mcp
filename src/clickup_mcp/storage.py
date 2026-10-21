"""MongoDB token store with async client support.

Tokens are scoped to (user_id, persona_id, workspace_id):
  - user_id     : Twynity account (JWT sub) — the owner
  - persona_id  : X-Persona-ID header — active persona/workspace selector
  - workspace_id: ClickUp workspace id
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from pymongo import AsyncMongoClient
from pymongo.errors import OperationFailure

from clickup_mcp.config import Settings


# Module-level active store set by lifespan
_active_store: Optional["TokenStore"] = None


def set_active_store(store: Optional["TokenStore"]) -> None:
    global _active_store
    _active_store = store


def get_active_store() -> Optional["TokenStore"]:
    return _active_store


class TokenStore:
    """MongoDB token store with async connection."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._client: Optional[AsyncMongoClient] = None
        self._db = None
        self._collection = None
        self._oauth_collection = None
        self._session_collection = None

    @property
    def _ensure_client(self):
        if self._client is None:
            self._client = AsyncMongoClient(
                self._settings.MONGODB_URI,
                serverSelectionTimeoutMS=5000,
            )
            self._db = self._client[self._settings.MONGODB_DB_NAME]
            self._collection = self._db[self._settings.MONGODB_COLLECTION]
            self._oauth_collection = self._db[self._settings.MONGODB_OAUTH_COLLECTION]
            self._session_collection = self._db[self._settings.MONGODB_SESSION_COLLECTION]
            self._ensure_index(self._collection, "user_id")
            self._ensure_index(self._collection, "persona_id")
            self._ensure_index(self._collection, "workspace_id")
            self._ensure_index(self._oauth_collection, "user_id")
            self._ensure_index(self._oauth_collection, "persona_id")
            self._ensure_index(self._oauth_collection, "workspace_id")
            self._ensure_index(self._session_collection, "state", unique=True)
        return self._client

    @property
    def _ensure_collection(self):
        if self._collection is None:
            self._ensure_client
        return self._collection

    @property
    def _ensure_oauth_collection(self):
        if self._oauth_collection is None:
            self._ensure_client
        return self._oauth_collection

    @property
    def _ensure_session_collection(self):
        if self._session_collection is None:
            self._ensure_client
        return self._session_collection

    @staticmethod
    def _ensure_index(collection, key: str, **kwargs) -> None:
        existing = collection.index_information()
        index_name = key + "_1"
        if index_name in existing:
            return
        try:
            collection.create_index(key, **kwargs)
        except OperationFailure as exc:
            error_code = getattr(exc, "code", None)
            if error_code in (85, 68):
                return
            raise

    # ---- PAT tokens (api_tokens collection) ----

    async def save_token(self, user_id, persona_id, workspace_id, encrypted_token):
        now = datetime.now(timezone.utc)
        q = {"user_id": user_id, "persona_id": persona_id, "workspace_id": workspace_id}
        existing = await self._ensure_collection.find_one(q)
        doc = dict(q)
        doc.update({
            "encrypted_token": encrypted_token,
            "created_at": existing.get("created_at", now) if existing else now,
            "updated_at": now,
        })
        await self._ensure_collection.replace_one(q, doc, upsert=True)

    async def get_token(self, user_id, persona_id, workspace_id):
        return await self._ensure_collection.find_one(
            {"user_id": user_id, "persona_id": persona_id, "workspace_id": workspace_id}
        )

    async def get_all_tokens(self, user_id, persona_id=None):
        q = {"user_id": user_id}
        if persona_id:
            q["persona_id"] = persona_id
        cursor = await self._ensure_collection.find(q)
        return await cursor.to_list(length=None)

    async def delete_token(self, user_id, persona_id, workspace_id):
        result = await self._ensure_collection.delete_one(
            {"user_id": user_id, "persona_id": persona_id, "workspace_id": workspace_id}
        )
        return result.deleted_count > 0

    async def list_workspaces(self, user_id, persona_id=None):
        q = {"user_id": user_id}
        if persona_id:
            q["persona_id"] = persona_id
        cursor = await self._ensure_collection.distinct("workspace_id", q)
        return await cursor.to_list(length=None)

    # ---- OAuth2 tokens (oauth_tokens collection) ----

    async def save_oauth_token(self, user_id, persona_id, workspace_id, encrypted_access_token, encrypted_refresh_token, expires_at):
        now = datetime.now(timezone.utc)
        q = {"user_id": user_id, "persona_id": persona_id, "workspace_id": workspace_id}
        existing = await self._ensure_oauth_collection.find_one(q)
        doc = dict(q)
        doc.update({
            "encrypted_access_token": encrypted_access_token,
            "encrypted_refresh_token": encrypted_refresh_token,
            "expires_at": expires_at,
            "created_at": existing.get("created_at", now) if existing else now,
            "updated_at": now,
        })
        await self._ensure_oauth_collection.replace_one(q, doc, upsert=True)

    async def get_oauth_token(self, user_id, persona_id, workspace_id):
        return await self._ensure_oauth_collection.find_one(
            {"user_id": user_id, "persona_id": persona_id, "workspace_id": workspace_id}
        )

    async def get_oauth_tokens_by_persona(self, user_id, persona_id=None):
        q = {"user_id": user_id}
        if persona_id:
            q["persona_id"] = persona_id
        cursor = await self._ensure_oauth_collection.find(q)
        return await cursor.to_list(length=None)

    async def delete_oauth_token(self, user_id, persona_id, workspace_id):
        result = await self._ensure_oauth_collection.delete_one(
            {"user_id": user_id, "persona_id": persona_id, "workspace_id": workspace_id}
        )
        return result.deleted_count > 0

    async def delete_all_oauth_tokens(self, user_id, persona_id=None):
        q = {"user_id": user_id}
        if persona_id:
            q["persona_id"] = persona_id
        result = await self._ensure_oauth_collection.delete_many(q)
        return result.deleted_count

    async def list_oauth_workspaces(self, user_id, persona_id=None):
        q = {"user_id": user_id}
        if persona_id:
            q["persona_id"] = persona_id
        cursor = await self._ensure_oauth_collection.distinct("workspace_id", q)
        return await cursor.to_list(length=None)

    # ---- OAuth sessions (oauth_sessions collection) ----

    async def save_session(self, state, session_data):
        doc = {
            "state": state,
            "session_data": session_data,
            "created_at": datetime.now(timezone.utc),
        }
        await self._ensure_session_collection.replace_one({"state": state}, doc, upsert=True)

    async def get_session(self, state):
        return await self._ensure_session_collection.find_one({"state": state})

    async def delete_session(self, state):
        result = await self._ensure_session_collection.delete_one({"state": state})
        return result.deleted_count > 0

    @property
    def client(self):
        return self._client
