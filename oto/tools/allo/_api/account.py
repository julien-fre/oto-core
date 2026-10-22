"""Allo team: its members and its lines. Composed into `AlloClient`, which provides the transport (`_request`)."""
from __future__ import annotations

from typing import Any, Optional

from ._common import _choice, _segment


class _AccountMixin:
    """The team's members and phone numbers."""

    def list_users(self, *, role: Optional[str] = None, status: Optional[str] = None) -> Any:
        """The team's members: id, name, email, role, status."""
        return self._request("GET", "/v2/api/users", params={
            "role": _choice("role", role, ("ADMIN", "MANAGER", "MEMBER")),
            "status": _choice("status", status, ("ACTIVE", "BLOCKED"))})

    def get_user(self, user_id: str) -> Any:
        """One member of the team (`usr-*`)."""
        return self._request("GET", f"/v2/api/users/{_segment(user_id, 'user_id')}")

    def list_numbers(self) -> Any:
        """The team's phone numbers and sender ids, with their members."""
        return self._request("GET", "/v2/api/numbers")
