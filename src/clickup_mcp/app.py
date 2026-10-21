"""Legacy entry point — imports the FastMCP app from main.py.

The actual FastMCP application is defined in ``main.py``.
This module re-exports the app for backwards compatibility.
"""

from clickup_mcp.main import app, mcp

__all__ = ["app", "mcp"]
