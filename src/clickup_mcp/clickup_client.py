from __future__ import annotations

import httpx
from typing import Any, Optional

from clickup_mcp.config import Settings


class ClickUpAPIError(Exception):
    def __init__(self, status_code: int, message: str, code: Optional[str] = None) -> None:
        self.status_code = status_code
        self.message = message
        self.code = code
        super().__init__(f"ClickUp API error {status_code}: {message}")


class ClickUpClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._base_url = settings.CLICKUP_API_BASE.rstrip("/")
        self._access_token: str = ""

    def _build_headers(self) -> dict[str, str]:
        headers: dict[str, str] = {
            "Content-Type": "application/json",
            "User-Agent": "ClickUpMCP/1.0",
        }
        if self._access_token:
            headers["Authorization"] = self._access_token
        return headers

    async def _request(
        self,
        method: str,
        path: str,
        headers: dict[str, str],
        params: Optional[dict] = None,
        json_body: Optional[dict] = None,
    ) -> dict[str, Any]:
        url = f"{self._base_url}{path}"
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.request(
                method=method,
                url=url,
                headers=headers,
                params=params,
                json=json_body,
            )
            if resp.status_code >= 400:
                try:
                    error_data = resp.json()
                    message = error_data.get("message", resp.text)
                    code = error_data.get("code")
                except Exception:
                    message = resp.text
                    code = None
                raise ClickUpAPIError(
                    status_code=resp.status_code,
                    message=message,
                    code=code,
                )
            if resp.status_code == 204 or (resp.status_code == 201 and not resp.text):
                return {}
            return resp.json()

    async def validate_token(self, token: str) -> dict[str, Any]:
        client = self.__class__(self.settings)
        client._access_token = token
        return await client._request(
            "GET",
            "/team",
            client._build_headers(),
        )

    async def get_workspace(self, workspace_id: str) -> dict[str, Any]:
        return await self._request(
            "GET",
            f"/workspace/{workspace_id}",
            self._build_headers(),
        )

    async def get_workspace_teams(self, workspace_id: str) -> dict[str, Any]:
        return await self._request(
            "GET",
            f"/team/{workspace_id}",
            self._build_headers(),
        )

    async def get_space_tasks(
        self,
        space_id: str,
        status: Optional[str] = None,
        assignee: Optional[str] = None,
        priority: Optional[str] = None,
        page_size: int = 25,
        cursor: Optional[str] = None,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"page_size": page_size}
        if status:
            params["status"] = status
        if assignee:
            params["assignee"] = assignee
        if priority:
            params["priority"] = priority
        if cursor:
            params["cursor"] = cursor
        return await self._request(
            "GET",
            f"/space/{space_id}",
            self._build_headers(),
            params=params,
        )

    async def get_list_tasks(
        self,
        list_id: str,
        status: Optional[str] = None,
        assignee: Optional[str] = None,
        priority: Optional[str] = None,
        page_size: int = 25,
        cursor: Optional[str] = None,
        include_archived: bool = False,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"page_size": page_size}
        if status:
            params["status"] = status
        if assignee:
            params["assignee"] = assignee
        if priority:
            params["priority"] = priority
        if cursor:
            params["cursor"] = cursor
        if include_archived:
            params["include_archived"] = "true"
        return await self._request(
            "GET",
            f"/list/{list_id}",
            self._build_headers(),
            params=params,
        )

    async def create_task(
        self,
        list_id: str,
        name: str,
        description: str = "",
        priority: Optional[str] = None,
        status: Optional[str] = None,
        assignee: Optional[str] = None,
        due_date: Optional[str] = None,
        tags: Optional[list[int]] = None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "name": name,
            "description": description,
        }
        if priority:
            body["priority"] = priority
        if status:
            body["status"] = status
        if assignee:
            body["assignee"] = assignee
        if due_date:
            body["due_date"] = due_date
        if tags:
            body["tags"] = tags
        return await self._request(
            "POST",
            f"/list/{list_id}/task",
            self._build_headers(),
            json_body=body,
        )

    async def get_task(self, task_id: str) -> dict[str, Any]:
        return await self._request(
            "GET",
            f"/task/{task_id}",
            self._build_headers(),
        )

    async def get_task_statuses(self, space_id: str) -> dict[str, Any]:
        return await self._request(
            "GET",
            f"/space/{space_id}",
            self._build_headers(),
        )

    async def get_team_lists(
        self,
        team_id: str,
        list_id: Optional[str] = None,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {}
        if list_id:
            params["list_id"] = list_id
        return await self._request(
            "GET",
            f"/team/{team_id}/list",
            self._build_headers(),
            params=params,
        )

    async def get_folder_lists(
        self,
        folder_id: str,
    ) -> dict[str, Any]:
        return await self._request(
            "GET",
            f"/folder/{folder_id}/list",
            self._build_headers(),
        )

    async def get_space_lists(
        self,
        space_id: str,
    ) -> dict[str, Any]:
        return await self._request(
            "GET",
            f"/space/{space_id}/list",
            self._build_headers(),
        )

    async def get_oauth_authorization_url(
        self,
        state: str,
        redirect_uri: str,
        client_id: str,
        auth_base_url: str = "https://app.clickup.com",
    ) -> str:
        params = {
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "state": state,
        }
        return f"{auth_base_url}/oauth/authorize?{httpx.QueryParams(params)}"

    async def exchange_code_for_token(
        self,
        code: str,
        redirect_uri: str,
        client_id: str,
        client_secret: str,
        token_url: str = "https://api.clickup.com/api/v2/oauth/token",
    ) -> dict[str, Any]:
        data = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
            "client_id": client_id,
            "client_secret": client_secret,
        }
        async with httpx.AsyncClient(timeout=30.0) as httpx_client:
            resp = await httpx_client.post(
                url=token_url,
                data=data,
            )
            if resp.status_code >= 400:
                try:
                    error_data = resp.json()
                    message = error_data.get("message", resp.text)
                    code_field = error_data.get("code")
                except Exception:
                    message = resp.text
                    code_field = None
                raise ClickUpAPIError(
                    status_code=resp.status_code,
                    message=message,
                    code=code_field,
                )
            return resp.json()

    async def refresh_access_token(
        self,
        refresh_token: str,
        client_id: str,
        client_secret: str,
        token_url: str = "https://api.clickup.com/api/v2/oauth/token",
    ) -> dict[str, Any]:
        data = {
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": client_id,
            "client_secret": client_secret,
        }
        async with httpx.AsyncClient(timeout=30.0) as httpx_client:
            resp = await httpx_client.post(
                url=token_url,
                data=data,
            )
            if resp.status_code >= 400:
                try:
                    error_data = resp.json()
                    message = error_data.get("message", resp.text)
                    code_field = error_data.get("code")
                except Exception:
                    message = resp.text
                    code_field = None
                raise ClickUpAPIError(
                    status_code=resp.status_code,
                    message=message,
                    code=code_field,
                )
            return resp.json()

    async def revoke_token(
        self,
        token: str,
        client_id: str,
        client_secret: str,
        token_url: str = "https://api.clickup.com/api/v2/oauth/revoke",
    ) -> dict[str, Any]:
        data = {
            "token": token,
            "client_id": client_id,
            "client_secret": client_secret,
        }
        async with httpx.AsyncClient(timeout=30.0) as httpx_client:
            resp = await httpx_client.post(
                url=token_url,
                data=data,
            )
            if resp.status_code >= 400:
                try:
                    error_data = resp.json()
                    message = error_data.get("message", resp.text)
                    code_field = error_data.get("code")
                except Exception:
                    message = resp.text
                    code_field = None
                raise ClickUpAPIError(
                    status_code=resp.status_code,
                    message=message,
                    code=code_field,
                )
            return resp.json()
