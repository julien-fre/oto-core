"""Segments (the groups a Broadcast is sent to) and topics (the per-subject
opt-in/opt-out a contact manages from the unsubscribe page).

Never instantiated on its own: composed into `ResendClient`, which provides
the transport (`_get`, `_post`) and the checks (`_need`, `_page`, `_seg`).

A segment is internal: recipients never see its name. A topic is shown to
them, and THEY change their subscription to it — so topics are read here,
never written.
"""
from __future__ import annotations

from typing import Any, Optional


class _SegmentsMixin:
    """Segments: list, read, create."""

    def list_segments(self, *, limit: Optional[int] = None,
                      after: Optional[str] = None,
                      before: Optional[str] = None) -> Any:
        """GET /segments — `{object, has_more, data: [{id, name, created_at}]}`.

        Without `limit` the API returns every segment in one response."""
        return self._get("/segments", self._page(limit, after, before))

    def get_segment(self, segment_id: str) -> Any:
        """GET /segments/{segment_id} — `{object, id, name, created_at}`."""
        return self._get(f"/segments/{self._seg(segment_id, 'segment_id')}")

    def create_segment(self, name: str) -> Any:
        """POST /segments — `{object, id, name}`."""
        return self._post("/segments", {"name": self._need(name, "name").strip()})


class _TopicsMixin:
    """Topics: read-only."""

    def list_topics(self, *, limit: Optional[int] = None,
                    after: Optional[str] = None,
                    before: Optional[str] = None) -> Any:
        """GET /topics — `{object, has_more, data: [{id, name, description,
        default_subscription, visibility, created_at}]}`. Always paginated
        (20 per page when `limit` is omitted)."""
        return self._get("/topics", self._page(limit, after, before))

    def get_topic(self, topic_id: str) -> Any:
        """GET /topics/{topic_id}."""
        return self._get(f"/topics/{self._seg(topic_id, 'topic_id')}")
