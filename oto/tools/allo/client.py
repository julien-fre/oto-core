"""Allo API client (https://help.withallo.com/en/v2/api-reference/introduction) —
the calls and texts of an Allo team (business phone system with AI summaries),
the audio of a call as a file, its lines and members, tags and internal notes, its contacts CRM (people,
companies, deals), the Power Dialer queue, team analytics and SMS sending.

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
  and 120 s at most.
- **SMS**: from one of the team's numbers (`from_number`, recipient in the same
  country) or, for France, from a Sender ID verified by Allo (`sender_id`).
  A text is sent at once and billed per segment.
- **Dialing queue**: one current queue per user; the queue calls act on the
  key owner's queue unless `user_id` or `email` names a teammate.
- **Rate limits** per key: 20 reads and 5 writes per second. The client retries
  nothing, read or write: a 429 raises `UpstreamHTTPError` like any refusal, and
  the caller waits the `error.retry_after_seconds` of its body.
- **Errors** carry `error.code`, `error.message` and often `error.suggestion`.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional
from urllib.parse import quote

import requests

from ...connectors.files import FileOut, file_output
from ..common import raise_for_upstream
from ..common.credentials import require

_HTTP_TIMEOUT = (10, 60)  # (connect, read) — never an unbounded wait
BASE_URL = "https://api.withallo.com"

SORTS = ("DATE_DESC", "DATE_ASC", "NAME_ASC", "NAME_DESC", "CREATED_DESC", "CREATED_ASC")
CONVERSATION_ACTIONS = ("READ", "UNREAD", "ARCHIVE", "UNARCHIVE")
MAX_SIZE = 100
# The addresses of a call's recording: `recording_url`, `recording_download_url` (signed, 48 hours, no login) and its
# expiry. They never leave the client; the audio comes as a file (`get_call_recording`).
RECORDING_ADDRESS_FIELDS = ("recording_url", "recording_download_url", "recording_download_expires_at")


def _segment(value: Any, name: str) -> str:
    """A path segment, percent-encoded whole (a `+`, a `/` never reshape the path)."""
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"`{name}` is required.")
    if text in (".", ".."):
        raise ValueError(f"`{name}` is not a valid value.")
    return quote(text, safe="")


def _choice(name: str, value: Optional[str], allowed: tuple) -> Optional[str]:
    if value is None:
        return None
    if value not in allowed:
        raise ValueError(f"`{name}` must be one of {', '.join(allowed)}.")
    return value


def _size(size: Optional[int]) -> Optional[int]:
    if size is not None and not 1 <= int(size) <= MAX_SIZE:
        raise ValueError(f"`size` must be from 1 to {MAX_SIZE}.")
    return size


def _clean(values: Dict[str, Any]) -> Dict[str, Any]:
    return {k: v for k, v in values.items() if v is not None}


def _without_addresses(item: Any) -> None:
    """Remove the recording addresses (`RECORDING_ADDRESS_FIELDS`) of one item; anything but an object is left as is."""
    if isinstance(item, dict):
        for field in RECORDING_ADDRESS_FIELDS:
            item.pop(field, None)


def _items_without_addresses(answer: Any, *, under: Optional[str] = None) -> Any:
    """The answer whose items (`data`, one object or a list), or the `under` key of each, lost their recording
    addresses; the rest of the answer (`pagination`) is kept."""
    if isinstance(answer, dict):
        data = answer.get("data")
        for entry in data if isinstance(data, list) else [data]:
            _without_addresses(entry.get(under) if under and isinstance(entry, dict) else entry)
    return answer


class AlloClient:
    """One method per endpoint of the Allo API served here."""

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

    def list_users(self, *, role: Optional[str] = None, status: Optional[str] = None) -> Any:
        """The team's members: id, name, email, role, status."""
        return self._request("GET", "/v2/api/users", params={
            "role": _choice("role", role, ("ADMIN", "MANAGER", "MEMBER")),
            "status": _choice("status", status, ("ACTIVE", "BLOCKED"))})

    def list_numbers(self) -> Any:
        """The team's phone numbers and sender ids, with their members."""
        return self._request("GET", "/v2/api/numbers")

    # --- conversations -----------------------------------------------------

    def list_conversations(self, allo_number: str, *, last_activity_since: Optional[str] = None,
                           unread: Optional[bool] = None, page: Optional[int] = None,
                           size: Optional[int] = None, extend: Optional[str] = None) -> Any:
        """The conversations of one line, by contact, most recent activity first; the
        last item of each without its recording addresses."""
        return _items_without_addresses(self._request("GET", "/v2/api/conversations", params={
            "allo_number": allo_number, "last_activity_since": last_activity_since,
            "unread": unread, "page": page, "size": _size(size), "extend": extend}), under="last_item")

    def search_conversation_items(self, *, allo_number: Optional[str] = None,
                                  contact_number: Optional[str] = None,
                                  user_id: Optional[str] = None, direction: Optional[str] = None,
                                  type: Optional[str] = None, result: Optional[str] = None,
                                  tags: Optional[List[str]] = None, unread: Optional[bool] = None,
                                  unresponded: Optional[bool] = None, search: Optional[str] = None,
                                  date: Optional[Dict[str, str]] = None, sort: Optional[str] = None,
                                  extend: Optional[str] = None, page: Optional[int] = None,
                                  size: Optional[int] = None) -> Any:
        """Calls and texts across every conversation, filtered, without their
        recording addresses; `search` is a keyword over transcripts, summaries and
        message content."""
        return _items_without_addresses(self._request("POST", "/v2/api/conversations/items/search", body={
            "allo_number": allo_number, "contact_number": contact_number, "user_id": user_id,
            "direction": _choice("direction", direction, ("INBOUND", "OUTBOUND")),
            "type": _choice("type", type, ("CALL", "SMS", "ALL")),
            "result": _choice("result", result, ("ANSWERED", "VOICEMAIL", "TRANSFERRED")),
            "tags": tags, "unread": unread, "unresponded": unresponded, "search": search,
            "date": date, "sort": _choice("sort", sort, ("DATE_DESC", "DATE_ASC", "RELEVANCE")),
            "extend": extend, "page": page, "size": _size(size)}))

    def get_conversation_item(self, item_id: str, *, extend: Optional[str] = None) -> Any:
        """One call (`cll-*`) or text (`msg-*`), without its recording addresses."""
        return _items_without_addresses(self._request(
            "GET", f"/v2/api/conversations/items/{_segment(item_id, 'item_id')}", params={"extend": extend}))

    def get_conversation_items(self, ids: List[str]) -> Any:
        """Several items by id in one request, without their recording addresses."""
        if not ids:
            raise ValueError("`ids` must list at least one item id.")
        return _items_without_addresses(
            self._request("POST", "/v2/api/conversations/items/batch", body={"ids": list(ids)}))

    def get_call_recording(self, item_id: str) -> FileOut:
        """The recording of one call (`cll-*`), as a file (`call-<id>-recording.mp3`).

        Raises `UpstreamHTTPError` when the API refuses the call (404: unknown call, or no recording; 403: the key's
        user may not play it, or a HIPAA-enabled team), `FileOutputError` when the file is refused, `requests.Timeout`
        beyond the 120 s of the function."""
        segment = _segment(item_id, "item_id")
        answer = self._send("GET", f"/v2/api/conversations/items/{segment}/recording", stream=True)
        return file_output("allo", "get_call_recording", answer=answer, args={"item_id": str(item_id).strip()},
                           session=self.session, base_url=BASE_URL)

    def update_call_summary(self, item_id: str, content: str, *,
                            template_key: Optional[str] = None) -> Any:
        """Replace the markdown of a call's AI summary."""
        return self._request(
            "PATCH", f"/v2/api/conversations/items/{_segment(item_id, 'item_id')}/summary",
            body={"content": content, "template_key": template_key})

    def update_conversation(self, contact_number: str, action: str, *,
                            allo_number: Optional[str] = None) -> Any:
        """Mark a conversation read or unread, archive or unarchive it."""
        return self._request(
            "PUT", f"/v2/api/conversations/{_segment(contact_number, 'contact_number')}/action",
            body={"action": _choice("action", action, CONVERSATION_ACTIONS),
                  "allo_number": allo_number})

    # --- tags --------------------------------------------------------------

    def list_tags(self) -> Any:
        return self._request("GET", "/v2/api/tags")

    def create_tag(self, name: str, *, color: Optional[str] = None) -> Any:
        """A team tag; its key is the slug of its name."""
        return self._request("POST", "/v2/api/tags", body={"name": name, "color": color})

    def add_item_tags(self, item_id: str, tags: List[str]) -> Any:
        """Tag a call with tag keys."""
        if not tags:
            raise ValueError("`tags` must list at least one tag key.")
        return self._request(
            "POST", f"/v2/api/conversations/items/{_segment(item_id, 'item_id')}/tags",
            body={"tags": list(tags)})

    def remove_item_tag(self, item_id: str, tag: str) -> Any:
        return self._request(
            "DELETE",
            f"/v2/api/conversations/items/{_segment(item_id, 'item_id')}/tags/{_segment(tag, 'tag')}")

    # --- notes -------------------------------------------------------------

    def list_conversation_notes(self, contact_number: str, allo_number: str, *,
                                page: Optional[int] = None, size: Optional[int] = None) -> Any:
        return self._request(
            "GET", f"/v2/api/conversations/{_segment(contact_number, 'contact_number')}/notes",
            params={"allo_number": allo_number, "page": page, "size": _size(size)})

    def create_conversation_note(self, contact_number: str, content: str, *,
                                 allo_number: Optional[str] = None,
                                 sender_id: Optional[str] = None) -> Any:
        """An internal team note on a conversation, never shown to the contact."""
        return self._request(
            "POST", f"/v2/api/conversations/{_segment(contact_number, 'contact_number')}/notes",
            body={"content": content, "allo_number": allo_number, "sender_id": sender_id})

    def list_person_notes(self, person_id: str, *, page: Optional[int] = None,
                          size: Optional[int] = None) -> Any:
        return self._request("GET", f"/v2/api/crm/people/{_segment(person_id, 'person_id')}/notes",
                             params={"page": page, "size": _size(size)})

    def create_person_note(self, person_id: str, content: str) -> Any:
        return self._request("POST", f"/v2/api/crm/people/{_segment(person_id, 'person_id')}/notes",
                             body={"content": content})

    # --- CRM ---------------------------------------------------------------

    def search_people(self, *, filters: Optional[Dict[str, Any]] = None,
                      search: Optional[str] = None, sort: Optional[str] = None,
                      page: Optional[int] = None, size: Optional[int] = None) -> Any:
        return self._request("POST", "/v2/api/crm/people/search", body={
            "filters": filters, "search": search, "sort": _choice("sort", sort, SORTS),
            "page": page, "size": _size(size)})

    def get_person(self, person_id: str) -> Any:
        return self._request("GET", f"/v2/api/crm/people/{_segment(person_id, 'person_id')}")

    def create_person(self, numbers: List[str], **fields: Any) -> Any:
        """A person; `fields`: name, last_name, job_title, website, address, emails,
        company_id, allow_duplicate_number, custom_attributes."""
        if not numbers:
            raise ValueError("`numbers` must list at least one phone number.")
        return self._request("POST", "/v2/api/crm/people", body={"numbers": list(numbers), **fields})

    def update_person(self, person_id: str, **fields: Any) -> Any:
        """Only the fields given change."""
        return self._request("PUT", f"/v2/api/crm/people/{_segment(person_id, 'person_id')}",
                             body=fields)

    def search_companies(self, *, filters: Optional[Dict[str, Any]] = None,
                         sort: Optional[str] = None, page: Optional[int] = None,
                         size: Optional[int] = None) -> Any:
        return self._request("POST", "/v2/api/crm/companies/search", body={
            "filters": filters, "sort": _choice("sort", sort, SORTS),
            "page": page, "size": _size(size)})

    def get_company(self, company_id: str) -> Any:
        return self._request("GET", f"/v2/api/crm/companies/{_segment(company_id, 'company_id')}")

    def create_company(self, name: str, **fields: Any) -> Any:
        """A company; `fields`: website, industry, custom_attributes."""
        return self._request("POST", "/v2/api/crm/companies", body={"name": name, **fields})

    def update_company(self, company_id: str, **fields: Any) -> Any:
        return self._request("PUT", f"/v2/api/crm/companies/{_segment(company_id, 'company_id')}",
                             body=fields)

    def search_deals(self, *, filters: Optional[Dict[str, Any]] = None,
                     search: Optional[str] = None, sort: Optional[str] = None,
                     page: Optional[int] = None, size: Optional[int] = None) -> Any:
        return self._request("POST", "/v2/api/crm/deals/search", body={
            "filters": filters, "search": search, "sort": _choice("sort", sort, SORTS),
            "page": page, "size": _size(size)})

    def get_deal(self, deal_id: str) -> Any:
        return self._request("GET", f"/v2/api/crm/deals/{_segment(deal_id, 'deal_id')}")

    def list_person_attributes(self, *, page: Optional[int] = None,
                               size: Optional[int] = None) -> Any:
        """The custom fields of people (created or synced from a CRM)."""
        return self._request("GET", "/v2/api/crm/attributes",
                             params={"page": page, "size": _size(size)})

    def list_company_attributes(self, *, page: Optional[int] = None,
                                size: Optional[int] = None) -> Any:
        return self._request("GET", "/v2/api/crm/companies/attributes",
                             params={"page": page, "size": _size(size)})

    # --- Power Dialer queue ------------------------------------------------

    def get_dialing_queue(self, *, user_id: Optional[str] = None, email: Optional[str] = None,
                          page: Optional[int] = None, size: Optional[int] = None) -> Any:
        """The numbers of a user's current queue, by position, and the queue's settings."""
        return self._request("GET", "/v2/api/dialing-queues/current", params={
            "user_id": user_id, "email": email, "page": page, "size": _size(size)})

    def reset_dialing_queue(self, *, name: Optional[str] = None, user_id: Optional[str] = None,
                            email: Optional[str] = None) -> Any:
        """A fresh, empty queue for the user; the previous one is no longer current."""
        return self._request("POST", "/v2/api/dialing-queues/current", body={
            "name": name, "user_id": user_id, "email": email})

    def update_dialing_queue(self, *, name: Optional[str] = None,
                             voicemail_handling: Optional[str] = None,
                             do_not_disturb: Optional[str] = None, user_id: Optional[str] = None,
                             email: Optional[str] = None) -> Any:
        return self._request("PATCH", "/v2/api/dialing-queues/current", body={
            "name": name,
            "voicemail_handling": _choice("voicemail_handling", voicemail_handling,
                                          ("SKIP", "NO_SKIP")),
            "do_not_disturb": _choice("do_not_disturb", do_not_disturb, ("ENABLED", "DISABLED")),
            "user_id": user_id, "email": email})

    def add_queue_numbers(self, numbers: List[Dict[str, Any]], *, user_id: Optional[str] = None,
                          email: Optional[str] = None) -> Any:
        """Append numbers (each `{number, name?, last_name?, company?, …}`) to the
        queue, made if none exists; answers `added` and `skipped`."""
        if not numbers:
            raise ValueError("`numbers` must list at least one entry.")
        return self._request("POST", "/v2/api/dialing-queues/current/numbers", body={
            "numbers": list(numbers), "user_id": user_id, "email": email})

    def remove_queue_numbers(self, *, number: Optional[str] = None,
                             position: Optional[int] = None, unassigned: Optional[bool] = None,
                             user_id: Optional[str] = None, email: Optional[str] = None) -> Any:
        """Remove by `number`, `position` (0-based), both, or `unassigned=True`
        (every entry not yet called)."""
        if unassigned and (number is not None or position is not None):
            raise ValueError("`unassigned` cannot be combined with `number` or `position`.")
        if not unassigned and number is None and position is None:
            raise ValueError("Give `number`, `position`, or `unassigned=true`.")
        return self._request("DELETE", "/v2/api/dialing-queues/current/numbers", params={
            "number": number, "position": position, "unassigned": True if unassigned else None,
            "user_id": user_id, "email": email})

    # --- analytics ---------------------------------------------------------

    def get_team_metrics(self, date: Dict[str, str], *,
                         compare_date: Optional[Dict[str, str]] = None,
                         user_ids: Optional[List[str]] = None,
                         allo_numbers: Optional[List[str]] = None) -> Any:
        """Team KPIs over `date` ({from, to}), against `compare_date`, per user."""
        return self._request("POST", "/v2/api/analytics/overview", body={
            "date": date, "compare_date": compare_date, "user_ids": user_ids,
            "allo_numbers": allo_numbers})

    def get_outbound_metrics(self, date: Dict[str, str], *,
                             compare_date: Optional[Dict[str, str]] = None,
                             user_ids: Optional[List[str]] = None,
                             allo_numbers: Optional[List[str]] = None,
                             tags: Optional[List[str]] = None, granularity: Optional[str] = None,
                             extend: Optional[str] = None, stage: Optional[str] = None,
                             page: Optional[int] = None, size: Optional[int] = None) -> Any:
        """The outbound funnel (dials → connected → conversations → conversions,
        a conversion being a call carrying one of `tags`), its time series,
        heatmap and leaderboard; `extend="items"` with `stage` lists the calls."""
        if extend is not None and extend != "items":
            raise ValueError("`extend` only takes `items`.")
        if extend and not stage:
            raise ValueError("`extend=items` requires `stage`.")
        return self._request("POST", "/v2/api/analytics/outbound", body={
            "date": date, "compare_date": compare_date, "user_ids": user_ids,
            "allo_numbers": allo_numbers, "tags": tags,
            "granularity": _choice("granularity", granularity, ("DAY", "WEEK", "MONTH")),
            "extend": extend,
            "stage": _choice("stage", stage, ("DIAL", "CONNECTED", "CONVERSATION", "CONVERSION")),
            "page": page, "size": _size(size)})

    # --- SMS ---------------------------------------------------------------

    def send_sms(self, to: str, message: str, *, from_number: Optional[str] = None,
                 sender_id: Optional[str] = None) -> Any:
        """Send a text now: from one of the team's numbers (`from_number`), or
        from a Sender ID verified by Allo (`sender_id`, France)."""
        if (from_number is None) == (sender_id is None):
            raise ValueError("Give exactly one of `from_number` or `sender_id`.")
        return self._request("POST", "/v1/api/sms", body={
            "from": from_number, "sender_id": sender_id, "to": to, "message": message})
