"""Allo discussion threads: the team's comments on one call, text or conversation note.

Composed into `AlloClient`, which provides the transport (`_request`)."""
from __future__ import annotations

from typing import Any

from ..const import THREAD_ENTITY_TYPES
from ._common import _choice, _segment


def _entity_type(value: str) -> str:
    if value is None:
        raise ValueError("`entity_type` is required.")
    return _choice("entity_type", value, THREAD_ENTITY_TYPES)


class _ThreadsMixin:
    """One thread at most per item (`cth-*`), its comments (`thc-*`)."""

    def find_thread(self, entity_type: str, entity_id: str) -> Any:
        """The thread of one item, if any (zero or one)."""
        if not str(entity_id or "").strip():
            raise ValueError("`entity_id` is required.")
        return self._request("GET", "/v2/api/threads", params={
            "entity_type": _entity_type(entity_type), "entity_id": entity_id})

    def get_thread(self, thread_id: str) -> Any:
        """A thread with all its comments."""
        return self._request("GET", f"/v2/api/threads/{_segment(thread_id, 'thread_id')}")

    def create_thread(self, entity_type: str, entity_id: str, content: str) -> Any:
        """Start the thread of an item with its first comment."""
        return self._request("POST", "/v2/api/threads", body={
            "entity_type": _entity_type(entity_type), "entity_id": entity_id, "content": content})

    def add_thread_comment(self, thread_id: str, content: str) -> Any:
        return self._request("POST", f"/v2/api/threads/{_segment(thread_id, 'thread_id')}/comments",
                             body={"content": content})

    def update_thread_comment(self, comment_id: str, content: str) -> Any:
        """Replace a comment's content; only its author may."""
        return self._request("PATCH", f"/v2/api/threads/comments/{_segment(comment_id, 'comment_id')}",
                             body={"content": content})

    def resolve_thread(self, thread_id: str) -> Any:
        return self._request("POST", f"/v2/api/threads/{_segment(thread_id, 'thread_id')}/resolve")

    def unresolve_thread(self, thread_id: str) -> Any:
        return self._request("POST", f"/v2/api/threads/{_segment(thread_id, 'thread_id')}/unresolve")
