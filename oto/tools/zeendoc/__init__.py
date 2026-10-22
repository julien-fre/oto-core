"""Zeendoc document management (GED) client, read-only."""
from .auth import ZeendocAuthError
from .client import ZeendocClient

__all__ = ["ZeendocClient", "ZeendocAuthError"]
