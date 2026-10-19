from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from pymongo import MongoClient
from pymongo.collection import Collection
from pymongo.errors import OperationFailure

from clickup_mcp.config import Settings


class TokenStore:
    """MongoDB token store with lazy connection.

    MongoDB connection is deferred until the first database operation
    to avoid blocking application startup when MongoDB is unavailable.
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._client: Optional[MongoClient] = None
        self._db: Optional[Collection] = None
        self._collection: Optional[Collection] = None
        self._oauth_collection: Optional[Collection] = None
        self._session_collection: Optional[Collection] = None

    @property
    def _ensure_client(self) -> MongoClient:
        """Lazy initialization of MongoDB client and collections."""
        if self._client is None:
            self._client = MongoClient(
                self._settings.MONGODB_URI,
                serverSelectionTimeoutMS=5000,
            )
            self._db = self._client[self._settings.MONGODB_DB_NAME]
            self._collection = self._db[self._settings.MONGODB_COLLECTION]
            self._oauth_collection = self._db[self._settings.MONGODB_OAUTH_COLLECTION]
            self._session_collection = self._db[self._settings.MONGODB_SESSION_COLLECTION]
            self._ensure_index(self._collection, "persona_id", unique=True)
            self._ensure_index(self._collection, "workspace_id")
            self._ensure_index(self._oauth_collection, "persona_id")
            self._ensure_index(self._oauth_collection, "workspace_id")
            self._ensure_index(self._oauth_collection, "access_token", sparse=True, unique=True)
            self._ensure_index(self._session_collection, "state", unique=True)
        return self._client

    @property
    def _ensure_collection(self) -> Collection:
        if self._collection is None:
            self._ensure_client
        return self._collection  # type: ignore[return-value]

    @property
    def _ensure_oauth_collection(self) -> Collection:
        if self._oauth_collection is None:
            self._ensure_client
        return self._oauth_collection  # type: ignore[return-value]

    @property
    def _ensure_session_collection(self) -> Collection:
        if self._session_collection is None:
            self._ensure_client
        return self._session_collection  # type: ignore[return-value]

    @staticmethod
    def _ensure_index(collection: Collection, key: str, **kwargs) -> None:
        """Create a unique index on the collection if it does not already exist.

        Uses ifNotExists pattern: always attempts to create the index and
        silently catches OperationFailure codes 85 (IndexOptionsConflict)
        and 68 (IndexNotFound) to handle race conditions where another
        instance creates the index concurrently. Skips index creation if
        the index already exists in index_information().
        """
        existing = collection.index_information()
        index_name = f"{key}_1"
        if index_name in existing:
            return
        try:
            collection.create_index(key, **kwargs)
        except OperationFailure as exc:
            error_code = getattr(exc, "code", None)
            if error_code in (85, 68):
                return
            raise

    async def save_token(
        self,
        persona_id: str,
        workspace_id: str,
        encrypted_token: dict,
    ) -> None:
        now = datetime.now(timezone.utc)
        existing = self._ensure_collection.find_one(
            {"persona_id": persona_id, "workspace_id": workspace_id}
        )
        doc = {
            "persona_id": persona_id,
            "workspace_id": workspace_id,
            "encrypted_token": encrypted_token,
            "created_at": existing.get("created_at", now) if existing else now,
            "updated_at": now,
        }
        self._ensure_collection.replace_one(
            {"persona_id": persona_id, "workspace_id": workspace_id},
            doc,
            upsert=True,
        )

    async def get_token(
        self, persona_id: str, workspace_id: str
    ) -> Optional[dict]:
        return self._ensure_collection.find_one(
            {"persona_id": persona_id, "workspace_id": workspace_id}
        )

    async def get_all_tokens(self, persona_id: str) -> list[dict]:
        cursor = self._ensure_collection.find({"persona_id": persona_id})
        return list(cursor)

    async def delete_token(
        self, persona_id: str, workspace_id: str
    ) -> bool:
        result = self._ensure_collection.delete_one(
            {"persona_id": persona_id, "workspace_id": workspace_id}
        )
        return result.deleted_count > 0

    async def list_workspaces(self, persona_id: str) -> list[str]:
        cursor = self._ensure_collection.distinct("workspace_id", {"persona_id": persona_id})
        return cursor

    # OAuth2 token storage methods

    async def save_oauth_token(
        self,
        persona_id: str,
        workspace_id: str,
        encrypted_access_token: dict,
        encrypted_refresh_token: dict,
        expires_at: int,
    ) -> None:
        now = datetime.now(timezone.utc)
        existing = self._ensure_oauth_collection.find_one(
            {"persona_id": persona_id, "workspace_id": workspace_id}
        )
        doc = {
            "persona_id": persona_id,
            "workspace_id": workspace_id,
            "encrypted_access_token": encrypted_access_token,
            "encrypted_refresh_token": encrypted_refresh_token,
            "expires_at": expires_at,
            "created_at": existing.get("created_at", now) if existing else now,
            "updated_at": now,
        }
        self._ensure_oauth_collection.replace_one(
            {"persona_id": persona_id, "workspace_id": workspace_id},
            doc,
            upsert=True,
        )

    async def get_oauth_token(
        self, persona_id: str, workspace_id: str
    ) -> Optional[dict]:
        return self._ensure_oauth_collection.find_one(
            {"persona_id": persona_id, "workspace_id": workspace_id}
        )

    async def get_oauth_tokens_by_persona(self, persona_id: str) -> list[dict]:
        cursor = self._ensure_oauth_collection.find({"persona_id": persona_id})
        return list(cursor)

    async def delete_oauth_token(
        self, persona_id: str, workspace_id: str
    ) -> bool:
        result = self._ensure_oauth_collection.delete_one(
            {"persona_id": persona_id, "workspace_id": workspace_id}
        )
        return result.deleted_count > 0

    async def delete_all_oauth_tokens(self, persona_id: str) -> int:
        result = self._ensure_oauth_collection.delete_many({"persona_id": persona_id})
        return result.deleted_count

    async def list_oauth_workspaces(self, persona_id: str) -> list[str]:
        cursor = self._ensure_oauth_collection.distinct("workspace_id", {"persona_id": persona_id})
        return cursor

    # Session storage methods

    async def save_session(self, state: str, session_data: dict) -> None:
        doc = {
            "state": state,
            "session_data": session_data,
            "created_at": datetime.now(timezone.utc),
        }
        self._ensure_session_collection.replace_one(
            {"state": state},
            doc,
            upsert=True,
        )

    async def get_session(self, state: str) -> Optional[dict]:
        return self._ensure_session_collection.find_one({"state": state})

    async def delete_session(self, state: str) -> bool:
        result = self._ensure_session_collection.delete_one({"state": state})
        return result.deleted_count > 0

    @property
    def client(self) -> Optional[MongoClient]:
        return self._client
