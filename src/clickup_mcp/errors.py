from __future__ import annotations

from typing import Optional


class MCPError(Exception):
    def __init__(
        self,
        code: str,
        message: str,
        detail: Optional[dict] = None,
    ) -> None:
        self.code = code
        self.message = message
        self.detail = detail or {}
        super().__init__(self.message)


class AuthError(MCPError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(code=code, message=message, detail={})


class StorageError(MCPError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(code=code, message=message, detail={})


class ConnectionError(MCPError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(code=code, message=message, detail={})
