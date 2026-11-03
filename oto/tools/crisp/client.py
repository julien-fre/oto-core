"""Crisp REST API V1 client (https://docs.crisp.chat/references/rest-api/v1/) —
read-only: the workspace (website), its inboxes, conversations and their
messages, contacts (people profiles) and the knowledge base (helpdesk).

The client of the `crisp` description (`connectors/crisp/connector.yaml`): one
method per function, named like it, with its arguments; responses are returned
as parsed JSON, unchanged (`{error, reason, data}`).

## Account

A website token: an identifier and a key, sent as HTTP Basic
`token_identifier:token_key` with the header `X-Crisp-Tier: website`. It
reaches only the workspace it was generated for. The `website_id` is not part
of the token: it is a setting of the account, and every path starts with
`/website/{website_id}`.

## Protocol facts that shape a caller

- **Paging by page number in the path**, from 1. Conversations and contacts
  take `per_page` (20 to 50, default 20). No response gives a total or a next
  page.
- **Dates.** `filter_date_start` / `filter_date_end` are ISO 8601 date-times
  (with their offset or `Z`); they bound the UPDATE date of a conversation, the
  CREATION date of a contact, the update date of a knowledge base entry. A
  date-time without an offset is refused rather than guessed.
- **Messages are paged by timestamp** (milliseconds): without argument, the
  latest batch; `timestamp_before` towards older messages, `timestamp_after`
  towards newer ones, `timestamp_around` centred on one.
- **A knowledge base tree path holds `/`** (`getting-started/install`): it is
  sent as path segments, each one percent-encoded, `/` kept between them; an
  empty, `.` or `..` segment is refused.
- **Flags** (`include_empty`, `filter_unread`…) are 0 or 1; `True` / `False`
  are accepted and sent as 1 / 0.
- **Rate limit: 10,000 requests per day per website token.** A 420 or 429 is
  never retried here: a daily counter does not reset within a request.
"""
from __future__ import annotations

import base64
import re
from datetime import datetime
from typing import Any, Dict, Optional, Union
from urllib.parse import quote

import requests

from ..common import raise_for_upstream
from ..common.credentials import require

_HTTP_TIMEOUT = (10, 60)  # (connect, read) — never an unbounded wait
BASE_URL = "https://api.crisp.chat/v1"

MIN_PER_PAGE, MAX_PER_PAGE = 20, 50
SEARCH_TYPES = ("text", "segment")
SORT_ORDERS = ("ascending", "descending")
CONTENT_TYPES = ("articles", "guides", "references", "news")
ENTRY_STATUSES = ("visible", "hidden", "draft", "featured")

_WEBSITE_ID = re.compile(r"^[A-Za-z0-9-]+$")

Flag = Union[bool, int, None]


def basic_signature(token_identifier: str, token_key: str) -> str:
    """`base64(identifier:key)` — the value that follows « Basic »."""
    return base64.b64encode(f"{token_identifier}:{token_key}".encode("utf-8")).decode("ascii")


def _segment(value: Any, name: str) -> str:
    """One path segment: a non-empty string, never `.` or `..`, percent-encoded
    (`@` kept, so that an email stays readable)."""
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"`{name}` must be a non-empty string; got {value!r}.")
    if value in (".", ".."):
        raise ValueError(f"`{name}` cannot be {value!r}.")
    return quote(value, safe="@")


def _tree_path(value: Any) -> str:
    """A knowledge base tree path: its segments encoded one by one, `/` kept."""
    if not isinstance(value, str) or not value.strip("/ "):
        raise ValueError(f"`tree_path` must be a non-empty path; got {value!r}.")
    segments = value.strip("/").split("/")
    if any(s in ("", ".", "..") for s in segments):
        raise ValueError(f"`tree_path` {value!r} holds an empty, `.` or `..` segment.")
    return "/".join(quote(s, safe="@") for s in segments)


def _page_number(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"`page_number` must be an integer >= 1; got {value!r}.")
    return value


def _per_page(value: Any) -> Optional[int]:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or not MIN_PER_PAGE <= value <= MAX_PER_PAGE:
        raise ValueError(f"`per_page` must be between {MIN_PER_PAGE} and {MAX_PER_PAGE} "
                         f"(Crisp API bounds); got {value!r}.")
    return value


def _flag(value: Flag, name: str) -> Optional[int]:
    if value is None:
        return None
    if isinstance(value, bool):
        return int(value)
    if value in (0, 1) and isinstance(value, int):
        return value
    raise ValueError(f"`{name}` must be 0 or 1; got {value!r}.")


def _choice(value: Optional[str], name: str, allowed: tuple) -> Optional[str]:
    if value is None:
        return None
    if value not in allowed:
        raise ValueError(f"`{name}` invalid: {value!r}. Accepted values: "
                         + ", ".join(repr(a) for a in allowed))
    return value


def _date_time(value: Optional[str], name: str) -> Optional[str]:
    """An ISO 8601 date-time WITH its offset, sent as given."""
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"`{name}` must be an ISO 8601 date-time; got {value!r}.")
    text = value.strip()
    try:
        parsed = datetime.fromisoformat(text[:-1] + "+00:00" if text[-1:] in ("Z", "z") else text)
    except ValueError:
        raise ValueError(f"`{name}` unreadable: {value!r}. Expected an ISO 8601 date-time "
                         "with its offset (2026-03-01T17:00:00.000Z).") from None
    if parsed.tzinfo is None:
        raise ValueError(f"`{name}`: {value!r} has no offset. Add `Z` (UTC) or an offset "
                         "such as `+02:00`.")
    return text


def _timestamp(value: Optional[int], name: str) -> Optional[int]:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"`{name}` must be a timestamp in milliseconds (integer >= 0); got {value!r}.")
    return value


def _text(value: Any, name: str) -> Optional[str]:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"`{name}` must be a non-empty string; got {value!r}.")
    return value


class CrispClient:
    """Crisp REST API V1, read-only, on one workspace. Basic auth with a website token."""

    BASE_URL = BASE_URL

    def __init__(self, token_identifier: Optional[str] = None,
                 token_key: Optional[str] = None,
                 website_id: Optional[str] = None):
        """
        Args:
            token_identifier: identifier of the website token (Basic auth user name).
            token_key: key of the website token (Basic auth password), shown once.
            website_id: the workspace the token reads (Settings > Workspace
                Settings > Setup Instructions).
        """
        self.token_identifier = require(token_identifier, "CRISP_TOKEN_IDENTIFIER")
        self.token_key = require(token_key, "CRISP_TOKEN_KEY")
        self.website_id = require(website_id, "CRISP_WEBSITE_ID")
        if not isinstance(self.website_id, str) or not _WEBSITE_ID.match(self.website_id):
            raise ValueError(f"`website_id` must be letters, digits and `-`; got {self.website_id!r}.")
        self.base_url = f"{self.BASE_URL}/website/{self.website_id}"
        self.session = requests.Session()
        # Credentials in the HEADER only — never in the URL, which ends up in
        # exception messages, logs and error tracking.
        self.session.headers.update({
            "Authorization": f"Basic {basic_signature(self.token_identifier, self.token_key)}",
            "X-Crisp-Tier": "website",
            "Accept": "application/json",
        })

    # --- transport ----------------------------------------------------------

    def _get(self, path: str, params: Optional[Dict[str, Any]] = None) -> Any:
        """GET `path` under the workspace; a refusal of the API raises `UpstreamHTTPError`."""
        clean = {k: v for k, v in (params or {}).items() if v is not None}
        resp = self.session.request("GET", f"{self.base_url}{path}", params=clean or None,
                                    timeout=_HTTP_TIMEOUT)
        raise_for_upstream(resp, service="crisp")
        return resp.json() if resp.content else {}

    @staticmethod
    def _conversation_filters(*, per_page, include_empty, filter_inbox_id, filter_unread,
                              filter_resolved, filter_not_resolved, filter_assigned,
                              filter_unassigned, filter_date_start, filter_date_end,
                              order_date_created, order_date_updated,
                              order_date_waiting) -> Dict[str, Any]:
        return {
            "per_page": _per_page(per_page),
            "include_empty": _flag(include_empty, "include_empty"),
            "filter_inbox_id": _text(filter_inbox_id, "filter_inbox_id"),
            "filter_unread": _flag(filter_unread, "filter_unread"),
            "filter_resolved": _flag(filter_resolved, "filter_resolved"),
            "filter_not_resolved": _flag(filter_not_resolved, "filter_not_resolved"),
            "filter_assigned": _text(filter_assigned, "filter_assigned"),
            "filter_unassigned": _flag(filter_unassigned, "filter_unassigned"),
            "filter_date_start": _date_time(filter_date_start, "filter_date_start"),
            "filter_date_end": _date_time(filter_date_end, "filter_date_end"),
            "order_date_created": _flag(order_date_created, "order_date_created"),
            "order_date_updated": _flag(order_date_updated, "order_date_updated"),
            "order_date_waiting": _flag(order_date_waiting, "order_date_waiting"),
        }

    @staticmethod
    def _people_filters(*, per_page, sort_field, sort_order, filter_date_start,
                        filter_date_end) -> Dict[str, Any]:
        return {
            "per_page": _per_page(per_page),
            "sort_field": _text(sort_field, "sort_field"),
            "sort_order": _choice(sort_order, "sort_order", SORT_ORDERS),
            "filter_date_start": _date_time(filter_date_start, "filter_date_start"),
            "filter_date_end": _date_time(filter_date_end, "filter_date_end"),
        }

    @staticmethod
    def _tree(locale: Any, content_type: Any) -> str:
        """`{locale}/{content_type}`, the two segments every knowledge base path starts with."""
        if content_type is None:
            raise ValueError("`content_type` is required: " + ", ".join(CONTENT_TYPES) + ".")
        return f"{_segment(locale, 'locale')}/{_choice(content_type, 'content_type', CONTENT_TYPES)}"

    # --- workspace and inboxes ---------------------------------------------

    def get_website(self) -> Any:
        """GET / — the workspace: website_id, name, domain, logo, verified."""
        return self._get("/")

    def list_inboxes(self, page_number: int = 1) -> Any:
        """GET /inboxes/list/{page_number} — the inboxes, with their conditions."""
        return self._get(f"/inboxes/list/{_page_number(page_number)}")

    def get_inbox(self, inbox_id: str) -> Any:
        """GET /inbox/{inbox_id} — one inbox."""
        return self._get(f"/inbox/{_segment(inbox_id, 'inbox_id')}")

    # --- conversations ------------------------------------------------------

    def list_conversations(self, page_number: int = 1, *, per_page: Optional[int] = None,
                           include_empty: Flag = None, filter_inbox_id: Optional[str] = None,
                           filter_unread: Flag = None, filter_resolved: Flag = None,
                           filter_not_resolved: Flag = None, filter_assigned: Optional[str] = None,
                           filter_unassigned: Flag = None, filter_date_start: Optional[str] = None,
                           filter_date_end: Optional[str] = None, order_date_created: Flag = None,
                           order_date_updated: Flag = None, order_date_waiting: Flag = None) -> Any:
        """GET /conversations/{page_number} — conversations of every channel. The
        date filters bound the UPDATE date; `order_date_updated=1` orders by it."""
        return self._get(f"/conversations/{_page_number(page_number)}", self._conversation_filters(
            per_page=per_page, include_empty=include_empty, filter_inbox_id=filter_inbox_id,
            filter_unread=filter_unread, filter_resolved=filter_resolved,
            filter_not_resolved=filter_not_resolved, filter_assigned=filter_assigned,
            filter_unassigned=filter_unassigned, filter_date_start=filter_date_start,
            filter_date_end=filter_date_end, order_date_created=order_date_created,
            order_date_updated=order_date_updated, order_date_waiting=order_date_waiting))

    def search_conversations(self, page_number: int, search_query: str, *,
                             search_type: Optional[str] = None, per_page: Optional[int] = None,
                             include_empty: Flag = None, filter_inbox_id: Optional[str] = None,
                             filter_unread: Flag = None, filter_resolved: Flag = None,
                             filter_not_resolved: Flag = None, filter_assigned: Optional[str] = None,
                             filter_unassigned: Flag = None, filter_date_start: Optional[str] = None,
                             filter_date_end: Optional[str] = None, order_date_created: Flag = None,
                             order_date_updated: Flag = None, order_date_waiting: Flag = None) -> Any:
        """GET /conversations/{page_number}?search_query=… — a text search
        (`search_type` text, the default) or the conversations of a segment
        (`segment`); same filters as `list_conversations`."""
        params = {"search_query": _text(search_query, "search_query"),
                  "search_type": _choice(search_type, "search_type", SEARCH_TYPES)}
        params.update(self._conversation_filters(
            per_page=per_page, include_empty=include_empty, filter_inbox_id=filter_inbox_id,
            filter_unread=filter_unread, filter_resolved=filter_resolved,
            filter_not_resolved=filter_not_resolved, filter_assigned=filter_assigned,
            filter_unassigned=filter_unassigned, filter_date_start=filter_date_start,
            filter_date_end=filter_date_end, order_date_created=order_date_created,
            order_date_updated=order_date_updated, order_date_waiting=order_date_waiting))
        if params["search_query"] is None:
            raise ValueError("`search_query` is required.")
        return self._get(f"/conversations/{_page_number(page_number)}", params)

    def get_conversation(self, session_id: str) -> Any:
        """GET /conversation/{session_id} — one conversation."""
        return self._get(f"/conversation/{_segment(session_id, 'session_id')}")

    def get_conversation_meta(self, session_id: str) -> Any:
        """GET /conversation/{session_id}/meta — its metadata, the channel (`origin`) included."""
        return self._get(f"/conversation/{_segment(session_id, 'session_id')}/meta")

    def list_conversation_messages(self, session_id: str, *, timestamp_before: Optional[int] = None,
                                   timestamp_after: Optional[int] = None,
                                   timestamp_around: Optional[int] = None) -> Any:
        """GET /conversation/{session_id}/messages — a batch of messages, the
        latest without argument; timestamps in milliseconds."""
        return self._get(f"/conversation/{_segment(session_id, 'session_id')}/messages", {
            "timestamp_before": _timestamp(timestamp_before, "timestamp_before"),
            "timestamp_after": _timestamp(timestamp_after, "timestamp_after"),
            "timestamp_around": _timestamp(timestamp_around, "timestamp_around"),
        })

    # --- contacts -----------------------------------------------------------

    def list_people(self, page_number: int = 1, *, per_page: Optional[int] = None,
                    sort_field: Optional[str] = None, sort_order: Optional[str] = None,
                    filter_date_start: Optional[str] = None,
                    filter_date_end: Optional[str] = None) -> Any:
        """GET /people/profiles/{page_number} — contacts; the date filters bound
        the CREATION date of a profile."""
        return self._get(f"/people/profiles/{_page_number(page_number)}", self._people_filters(
            per_page=per_page, sort_field=sort_field, sort_order=sort_order,
            filter_date_start=filter_date_start, filter_date_end=filter_date_end))

    def search_people(self, page_number: int, search_text: str, *, per_page: Optional[int] = None,
                      sort_field: Optional[str] = None, sort_order: Optional[str] = None,
                      filter_date_start: Optional[str] = None,
                      filter_date_end: Optional[str] = None) -> Any:
        """GET /people/profiles/{page_number}?search_text=… — a quick text search."""
        text = _text(search_text, "search_text")
        if text is None:
            raise ValueError("`search_text` is required.")
        params = {"search_text": text}
        params.update(self._people_filters(
            per_page=per_page, sort_field=sort_field, sort_order=sort_order,
            filter_date_start=filter_date_start, filter_date_end=filter_date_end))
        return self._get(f"/people/profiles/{_page_number(page_number)}", params)

    def get_person(self, people_id: str) -> Any:
        """GET /people/profile/{people_id} — one contact, by people_id or email."""
        return self._get(f"/people/profile/{_segment(people_id, 'people_id')}")

    def get_person_data(self, people_id: str) -> Any:
        """GET /people/data/{people_id} — the custom data of one contact."""
        return self._get(f"/people/data/{_segment(people_id, 'people_id')}")

    def list_person_conversations(self, people_id: str, page_number: int = 1, *,
                                  filter_unread: Flag = None, filter_resolved: Flag = None,
                                  filter_not_resolved: Flag = None) -> Any:
        """GET /people/conversations/{people_id}/list/{page_number} — the
        session_id of one contact's conversations."""
        return self._get(
            f"/people/conversations/{_segment(people_id, 'people_id')}/list/{_page_number(page_number)}", {
                "filter_unread": _flag(filter_unread, "filter_unread"),
                "filter_resolved": _flag(filter_resolved, "filter_resolved"),
                "filter_not_resolved": _flag(filter_not_resolved, "filter_not_resolved"),
            })

    # --- knowledge base -----------------------------------------------------

    def get_helpdesk(self) -> Any:
        """GET /helpdesk — the knowledge base: name, url."""
        return self._get("/helpdesk")

    def list_helpdesk_locales(self, page_number: int = 1) -> Any:
        """GET /helpdesk/locales/{page_number} — its locales and their statistics."""
        return self._get(f"/helpdesk/locales/{_page_number(page_number)}")

    def list_helpdesk_pages(self, locale: str, content_type: str, page_number: int = 1) -> Any:
        """GET /helpdesk/page/list/{locale}/{content_type}/{page_number} — published pages."""
        return self._get(f"/helpdesk/page/list/{self._tree(locale, content_type)}/{_page_number(page_number)}")

    def list_helpdesk_tree(self, locale: str, content_type: str, page_number: int = 1, *,
                           sub_path: Optional[str] = None, search_title: Optional[str] = None,
                           search_filter_status: Optional[str] = None,
                           filter_date_start: Optional[str] = None,
                           filter_date_end: Optional[str] = None) -> Any:
        """GET /helpdesk/tree/list/{locale}/{content_type}/{page_number} — the
        tree, drafts and hidden entries included."""
        return self._get(f"/helpdesk/tree/list/{self._tree(locale, content_type)}/{_page_number(page_number)}", {
            "sub_path": _text(sub_path, "sub_path"),
            "search_title": _text(search_title, "search_title"),
            "search_filter_status": _choice(search_filter_status, "search_filter_status", ENTRY_STATUSES),
            "filter_date_start": _date_time(filter_date_start, "filter_date_start"),
            "filter_date_end": _date_time(filter_date_end, "filter_date_end"),
        })

    def get_helpdesk_entry(self, locale: str, content_type: str, tree_path: str) -> Any:
        """GET /helpdesk/tree/path/{locale}/{content_type}/{tree_path} — one entry."""
        return self._get(f"/helpdesk/tree/path/{self._tree(locale, content_type)}/{_tree_path(tree_path)}")

    def get_helpdesk_content(self, locale: str, content_type: str, tree_path: str) -> Any:
        """GET /helpdesk/tree/content/{locale}/{content_type}/{tree_path} — the body of one file."""
        return self._get(f"/helpdesk/tree/content/{self._tree(locale, content_type)}/{_tree_path(tree_path)}")

    def get_helpdesk_metadata(self, locale: str, content_type: str, tree_path: str) -> Any:
        """GET /helpdesk/tree/metadata/{locale}/{content_type}/{tree_path} — its metadata."""
        return self._get(f"/helpdesk/tree/metadata/{self._tree(locale, content_type)}/{_tree_path(tree_path)}")


__all__ = [
    "CrispClient", "basic_signature", "BASE_URL", "MIN_PER_PAGE", "MAX_PER_PAGE",
    "SEARCH_TYPES", "SORT_ORDERS", "CONTENT_TYPES", "ENTRY_STATUSES",
]
