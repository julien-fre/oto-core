"""YouTube — a channel's Studio surface with an OAuth2 user access token (REST).

`YouTubeClient` is the entry point: Data API v3 (channel, uploads, playlists, comments,
metadata and thumbnail writes) and Analytics API v2 (`reports.query`).
"""
from __future__ import annotations

from .client import (
    MAX_IDS,
    MODERATION_STATUSES,
    PRIVACY_STATUSES,
    SCOPES,
    THUMBNAIL_MAX_BYTES,
    THUMBNAIL_MIME_TYPES,
    VIDEO_FIELDS,
    YouTubeClient,
    YouTubeError,
    plan_video_update,
)

__all__ = [
    "MAX_IDS", "MODERATION_STATUSES", "PRIVACY_STATUSES", "SCOPES", "THUMBNAIL_MAX_BYTES",
    "THUMBNAIL_MIME_TYPES", "VIDEO_FIELDS", "YouTubeClient", "YouTubeError",
    "plan_video_update",
]
