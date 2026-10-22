"""Allo API client (https://help.withallo.com/en/v2/api-reference/introduction) —
the calls and texts of an Allo team (business phone system with AI summaries),
the audio of a call as a file, its lines and members, tags, internal notes and discussion threads, its contacts
CRM (people, companies, deals, custom fields), the Power Dialer queues and sessions, team analytics, SMS sending,
summary templates, webhooks, and the settings of a line: call flow, AI receptionist, calendars and voices.
Not served: the Partner API (`/v2/api/partner/*`), which takes a reseller key, not a team key.

Auth: an API key created under Settings → API by an Admin or a Manager, sent as
`Authorization: Api-Key <key>` (not Bearer). Its scopes bound what it reaches
(`CONVERSATIONS_READ`, `CRM_READ`, `CRM_WRITE`, `SMS_SEND`…); `get_me` lists them
with the endpoints the key may call. Host `https://api.withallo.com`; every path
carries its version (`/v2/api/…`, SMS on `/v1/api/sms`). Responses are returned
as parsed JSON, unchanged (`{"data": …}`, lists with `pagination`).

## Protocol facts that shape a caller

- **Pages are 1-indexed** (`page`, `size`); a list answers `pagination` with
  `total_count`, `total_pages` and `has_more`.
- **Phone numbers are E.164** (`+33199000001`). A conversation is keyed by the
  contact's number on one Allo line (`allo_number`); in a path the number is
  percent-encoded (`+` as `%2B`).
- **Item ids**: `cll-*` for a call, `msg-*` for a text. Only a call has a
  summary, tags and a recording.
- **The audio of a call is never a link** (description 1.1.0): Allo gives
  `recording_url`, `recording_download_url` (signed, 48 hours, plays without an
  Allo login) and its expiry on every call it returns, and a fresh signed link
  (60 minutes) at `/items/{id}/recording`. Every read of a call removes them
  (`RECORDING_ADDRESS_FIELDS`); `get_call_recording` downloads the audio at once
  and returns it as a `FileOut` (name, bytes, type), through
  `oto.connectors.files.file_output` and the declaration of the description:
  the signed link is fetched without the API key, no redirect followed, 50 MB
  and 120 s at most. No audio address leaves the client: `list_voices` drops
  `demo_url`, the address of a voice's sample.
- **No secret leaves the client**: the webhook calls drop `signing_secret`,
  which is read in Allo.
- **SMS**: from one of the team's numbers (`from_number`, recipient in the same
  country) or, for France, from a Sender ID verified by Allo (`sender_id`).
  A text is sent at once and billed per segment.
- **Dialing queue**: one current queue per user; the queue calls act on the
  key owner's queue unless `user_id` or `email` names a teammate. Named queues
  (`pdl-*`) are reached by id.
- **Destructive calls**: deleting a company attribute clears its value on every
  company, for good; deleting a person field keeps its values, and creating it
  again restores them. Publishing a call flow or switching the receptionist
  changes how a live line routes real calls.
- **Rate limits** per key: 20 reads and 5 writes per second. The client retries
  nothing, read or write: a 429 raises `UpstreamHTTPError` like any refusal, and
  the caller waits the `error.retry_after_seconds` of its body.
- **Errors** carry `error.code`, `error.message` and often `error.suggestion`.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

import requests

from ..common import raise_for_upstream
from ..common.credentials import require
from ._api import (_AccountMixin, _AnalyticsSmsMixin, _ConversationsMixin, _CrmMixin, _DialerMixin, _LinesMixin,
                   _TagsNotesMixin, _TemplatesWebhooksMixin, _ThreadsMixin)
from ._api._common import _clean
from .const import (_HTTP_TIMEOUT, ATTRIBUTE_TYPES, BASE_URL, CONVERSATION_ACTIONS, DO_NOT_DISTURB, MAX_SIZE,
                    RECORDING_ADDRESS_FIELDS, SORTS, THREAD_ENTITY_TYPES, VOICEMAIL_HANDLING, WEBHOOK_TOPICS)

__all__ = ["AlloClient", "BASE_URL", "SORTS", "CONVERSATION_ACTIONS", "MAX_SIZE", "RECORDING_ADDRESS_FIELDS",
           "ATTRIBUTE_TYPES", "THREAD_ENTITY_TYPES", "WEBHOOK_TOPICS", "VOICEMAIL_HANDLING", "DO_NOT_DISTURB"]


class AlloClient(_AccountMixin, _ConversationsMixin, _TagsNotesMixin, _ThreadsMixin, _CrmMixin, _DialerMixin,
                 _AnalyticsSmsMixin, _TemplatesWebhooksMixin, _LinesMixin):
    """One method per endpoint of the Allo API served here; the call families live in `_api/`."""

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = require(api_key, "ALLO_API_KEY")
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Api-Key {self.api_key}",
            "Accept": "application/json",
        })

    def _send(self, method: str, path: str, *, params: Optional[Dict[str, Any]] = None,
              body: Optional[Dict[str, Any]] = None, stream: bool = False) -> requests.Response:
        """One request, never retried; a refusal of the API raises `UpstreamHTTPError`."""
        # A boolean in the query is written `true`/`false`, never Python's `True`.
        clean = {k: (str(v).lower() if isinstance(v, bool) else v)
                 for k, v in _clean(params or {}).items()}
        resp = self.session.request(method, f"{BASE_URL}{path}", params=clean or None,
                                    json=_clean(body) if body is not None else None,
                                    timeout=_HTTP_TIMEOUT, stream=stream)
        raise_for_upstream(resp, service="allo")
        return resp

    def _request(self, method: str, path: str, *, params: Optional[Dict[str, Any]] = None,
                 body: Optional[Dict[str, Any]] = None) -> Any:
        resp = self._send(method, path, params=params, body=body)
        return resp.json() if resp.content else {}

    # --- account -----------------------------------------------------------

    def get_me(self) -> Any:
        """The key itself: its scopes, the endpoints it may call, the team, the
        rate limits. Needs no scope: the cheapest authenticated call."""
        return self._request("GET", "/v2/api/me")

    def probe(self) -> Any:
        return self.get_me()
