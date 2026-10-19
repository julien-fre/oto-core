"""Mux Video API client (https://docs.mux.com/api-reference) — assets (the
videos Mux stores and streams) and direct uploads (a signed address a file is
sent to, which becomes an asset).

HTTP Basic auth: the access token ID as user name, its secret key as password,
both created under Settings → Access Tokens with the Mux Video permission.
Host `https://api.mux.com`; every path carries its version (`/video/v1/…`).
Responses are returned as parsed JSON, unchanged (`{"data": …}`).

## Protocol facts that shape a caller

- **A direct upload is two steps.** `create_upload` answers an `url`: the file
  itself is then sent there with one `PUT` (no credential: the address is the
  authorisation), from wherever the file is. Mux makes the asset once the file
  has arrived; `get_upload` then carries its `asset_id`. An upload not used
  within `timeout` seconds (default 3600) expires.
- **An asset is ready asynchronously.** `status` goes `preparing` → `ready`
  (or `errored`); playback, `duration` and the resolution are known once
  `ready`. A one-minute film takes about a minute.
- **Playback** is by playback ID: `https://stream.mux.com/<playback_id>.m3u8`
  (HLS). A `public` policy plays for anyone with the address; a `signed` one
  needs a signed token, which this client does not make.
- **`create_asset` fetches a file from an address** Mux can reach (`https`,
  public or pre-signed) instead of an upload.
- **`test: true`** makes a free asset limited to 10 seconds, watermarked and
  deleted after 24 hours: for trying the flow, not for a real video.
- **`video_quality`**: `basic`, `plus` or `premium` (billed differently);
  **`max_resolution_tier`**: `1080p`, `1440p` or `2160p`.
- **Writes are not retried**: no idempotency key, a replay would make a second
  upload or asset. `passthrough` (up to 255 characters) is yours to set and is
  returned on the asset, e.g. to recognise it later.
"""
from __future__ import annotations

import base64
import re
from typing import Any, Dict, List, Optional

import requests

from ..common import raise_for_upstream
from ..common.credentials import require

_HTTP_TIMEOUT = (10, 60)  # (connect, read) — never an unbounded wait
BASE_URL = "https://api.mux.com"

PLAYBACK_POLICIES = ("public", "signed")
VIDEO_QUALITIES = ("basic", "plus", "premium")
RESOLUTION_TIERS = ("1080p", "1440p", "2160p")
MAX_LIMIT = 100
MAX_PASSTHROUGH = 255

_ID = re.compile(r"^[A-Za-z0-9]{1,128}$")


def basic_signature(token_id: str, token_secret: str) -> str:
    """`base64(token_id:token_secret)` — the value that follows « Basic »."""
    return base64.b64encode(f"{token_id}:{token_secret}".encode("utf-8")).decode("ascii")


def _object_id(value: Any, name: str) -> str:
    text = str(value or "").strip()
    if not _ID.match(text):
        raise ValueError(f"`{name}` must be a Mux id (letters and digits).")
    return text


def _choice(name: str, value: Optional[str], allowed: tuple) -> Optional[str]:
    if value is None:
        return None
    if value not in allowed:
        raise ValueError(f"`{name}` must be one of {', '.join(allowed)}.")
    return value


def _https(value: str, name: str) -> str:
    text = str(value or "").strip()
    if not text.startswith("https://"):
        raise ValueError(f"`{name}` must be an https:// address Mux can fetch.")
    return text


def _asset_settings(*, playback_policy: Optional[str], video_quality: Optional[str],
                    max_resolution_tier: Optional[str], passthrough: Optional[str],
                    title: Optional[str]) -> Dict[str, Any]:
    """The settings of a new asset, shared by an upload and an asset from an address."""
    if passthrough is not None and len(passthrough) > MAX_PASSTHROUGH:
        raise ValueError(f"`passthrough` is at most {MAX_PASSTHROUGH} characters.")
    settings: Dict[str, Any] = {
        "playback_policy": [_choice("playback_policy", playback_policy or "public", PLAYBACK_POLICIES)],
        "video_quality": _choice("video_quality", video_quality, VIDEO_QUALITIES),
        "max_resolution_tier": _choice("max_resolution_tier", max_resolution_tier, RESOLUTION_TIERS),
        "passthrough": passthrough,
        "meta": {"title": title} if title else None,
    }
    return {k: v for k, v in settings.items() if v is not None}


class MuxClient:
    """One method per endpoint of Mux Video's assets and direct uploads."""

    def __init__(self, token_id: Optional[str] = None, token_secret: Optional[str] = None):
        self.token_id = require(token_id, "MUX_TOKEN_ID")
        self.token_secret = require(token_secret, "MUX_TOKEN_SECRET")
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Basic {basic_signature(self.token_id, self.token_secret)}",
            "Accept": "application/json",
        })

    def _request(self, method: str, path: str, *, params: Optional[Dict[str, Any]] = None,
                 body: Optional[Dict[str, Any]] = None) -> Any:
        clean = {k: v for k, v in (params or {}).items() if v is not None}
        resp = self.session.request(method, f"{BASE_URL}{path}", params=clean or None, json=body,
                                    timeout=_HTTP_TIMEOUT)
        raise_for_upstream(resp, service="mux")
        return resp.json() if resp.content else {}

    # --- reads -------------------------------------------------------------

    def probe(self) -> Any:
        """Cheapest authenticated call: one asset of the environment."""
        return self.list_assets(limit=1)

    def list_assets(self, *, limit: Optional[int] = None, cursor: Optional[str] = None,
                    upload_id: Optional[str] = None) -> Any:
        """Assets of the token's environment, newest first. `next_cursor` in
        the answer pages on; `upload_id` finds the asset an upload made."""
        if limit is not None and not 1 <= int(limit) <= MAX_LIMIT:
            raise ValueError(f"`limit` must be from 1 to {MAX_LIMIT}.")
        return self._request("GET", "/video/v1/assets", params={
            "limit": limit, "cursor": cursor,
            "upload_id": _object_id(upload_id, "upload_id") if upload_id else None})

    def get_asset(self, asset_id: str) -> Any:
        """One asset: status, duration, resolution, playback IDs, tracks."""
        return self._request("GET", f"/video/v1/assets/{_object_id(asset_id, 'asset_id')}")

    def get_upload(self, upload_id: str) -> Any:
        """One direct upload: its status and, once the file arrived, `asset_id`."""
        return self._request("GET", f"/video/v1/uploads/{_object_id(upload_id, 'upload_id')}")

    # --- writes ------------------------------------------------------------

    def create_upload(self, *, cors_origin: Optional[str] = None,
                      playback_policy: Optional[str] = None, video_quality: Optional[str] = None,
                      max_resolution_tier: Optional[str] = None, passthrough: Optional[str] = None,
                      title: Optional[str] = None, timeout: Optional[int] = None,
                      test: Optional[bool] = None) -> Any:
        """A direct upload: answers the `url` to PUT the file to. Playback is
        public unless `playback_policy="signed"`."""
        if timeout is not None and not 60 <= int(timeout) <= 604800:
            raise ValueError("`timeout` must be from 60 to 604800 seconds.")
        body: Dict[str, Any] = {
            "new_asset_settings": _asset_settings(
                playback_policy=playback_policy, video_quality=video_quality,
                max_resolution_tier=max_resolution_tier, passthrough=passthrough, title=title),
            "cors_origin": cors_origin,
            "timeout": timeout,
            "test": test,
        }
        return self._request("POST", "/video/v1/uploads",
                             body={k: v for k, v in body.items() if v is not None})

    def create_asset(self, input_url: str, *, playback_policy: Optional[str] = None,
                     video_quality: Optional[str] = None, max_resolution_tier: Optional[str] = None,
                     passthrough: Optional[str] = None, title: Optional[str] = None,
                     test: Optional[bool] = None) -> Any:
        """An asset from a file Mux fetches at `input_url` (https)."""
        inputs: List[Dict[str, Any]] = [{"url": _https(input_url, "input_url")}]
        body: Dict[str, Any] = {
            "inputs": inputs,
            **_asset_settings(playback_policy=playback_policy, video_quality=video_quality,
                              max_resolution_tier=max_resolution_tier, passthrough=passthrough,
                              title=title),
            "test": test,
        }
        return self._request("POST", "/video/v1/assets",
                             body={k: v for k, v in body.items() if v is not None})
