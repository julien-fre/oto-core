"""
Resend API client — transactional sending, and the contact list Broadcasts
are sent to: contacts, segments, topics.

Two transports, kept apart:

- `send_email` / `ResendClient.send` go through the `resend` package (pip
  install resend), imported lazily;
- the contact, segment and topic methods are REST over `requests`, host
  `https://api.resend.com`, `Authorization: Bearer <key>`. One method per
  endpoint (plus `upsert_contact`); responses are returned as parsed JSON,
  unchanged.

This module holds construction, transport and the sending helpers, and
composes the call families of `_api/`. Constants live in `const.py` and are
re-exported here: the backend pins oto-core by tag and only imports
`oto.tools.resend.client`.

## Protocol facts that shape a caller

- **Contacts, segments and topics need a key with Full access.** A key
  restricted to sending is refused on these routes: 401 `restricted_api_key`
  ("This API key is restricted to only send emails"). An unknown or deleted
  key answers 400 `validation_error` ("API key is invalid") on them.
- **Errors are `{name, statusCode, message}`**; `name` is the stable code
  (`restricted_api_key`, `validation_error`, `not_found`,
  `rate_limit_exceeded`…). They surface as `UpstreamHTTPError` with that body.
- **Contacts are global to the account** and grouped by segments; a Broadcast
  goes to a segment. Topics carry a per-subject opt-in/opt-out that the
  recipient manages.
- **Rate limit: 10 requests per second per team**, all keys together. A
  client paces its own calls (`MIN_INTERVAL_S`), retries a read on 429/5xx,
  and never replays a write.
- **Redirects are refused, never followed.**
"""
from __future__ import annotations

import time
from typing import Optional, Dict, Any, List
from urllib.parse import quote

import requests

from ..common import raise_for_upstream
from ..common.credentials import require
from ..http.client import refuse_redirect
from ._api import _ContactsMixin, _SegmentsMixin, _TopicsMixin
from .const import (BASE_URL, HTTP_TIMEOUT, MAX_ATTEMPTS, MAX_PAGE_SIZE,
                    MAX_WALK_PAGES, MIN_INTERVAL_S, RATE_LIMIT_MAX_WAIT,
                    RETRY_STATUSES)


def send_email(
    to: str | List[str],
    subject: str,
    text: str = None,
    html: str = None,
    reply_to: str = None,
    from_email: str = None,
    api_key: str = None,
) -> Dict[str, Any]:
    """
    Send an email via Resend.

    Args:
        to: Recipient email(s)
        subject: Email subject
        text: Plain text body
        html: HTML body
        reply_to: Reply-to address
        from_email: Sender email (default from RESEND_FROM_EMAIL)
        api_key: API key (default from RESEND_API_KEY)

    Returns:
        Dict with id and success status
    """
    try:
        import resend
    except ImportError:
        raise ImportError("resend package required. Install with: pip install resend")

    resend.api_key = require(api_key, "RESEND_API_KEY")
    from_addr = from_email or "noreply@example.com"

    params = {
        "from": from_addr,
        "to": [to] if isinstance(to, str) else to,
        "subject": subject,
    }

    if text:
        params["text"] = text
    if html:
        params["html"] = html
    if reply_to:
        params["reply_to"] = reply_to

    result = resend.Emails.send(params)

    return {
        "success": True,
        "id": result.get("id"),
    }


class ResendClient(_ContactsMixin, _SegmentsMixin, _TopicsMixin):
    """
    Resend client — sending, and contacts / segments / topics.

    Usage:
        client = ResendClient(api_key="re_...")
        client.send(to="user@example.com", subject="Hello", text="Hi there!")
        client.upsert_contact("user@example.com", segment_ids=["<segment id>"])
    """

    BASE_URL = BASE_URL

    def __init__(self, api_key: str = None, from_email: str = None):
        """
        Initialize Resend client.

        Args:
            api_key: Resend API key (required). Contacts, segments and topics
                need a key with Full access; a sending-only key can only send.
            from_email: Default from email (default: noreply@example.com)
        """
        self.api_key = require(api_key, "RESEND_API_KEY")
        self.from_email = from_email or "noreply@example.com"
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {self.api_key}",
            "Accept": "application/json",
        })
        self._last_call: Optional[float] = None

    # --- sending (resend package) -------------------------------------------

    def send(
        self,
        to: str | List[str],
        subject: str,
        text: str = None,
        html: str = None,
        reply_to: str = None,
        from_email: str = None,
    ) -> Dict[str, Any]:
        """
        Send an email.

        Args:
            to: Recipient email(s)
            subject: Email subject
            text: Plain text body
            html: HTML body
            reply_to: Reply-to address
            from_email: Override sender email

        Returns:
            Dict with id and success status
        """
        return send_email(
            to=to,
            subject=subject,
            text=text,
            html=html,
            reply_to=reply_to,
            from_email=from_email or self.from_email,
            api_key=self.api_key,
        )

    def send_template(
        self,
        to: str | List[str],
        subject: str,
        template_html: str,
        variables: Dict[str, str] = None,
        reply_to: str = None,
    ) -> Dict[str, Any]:
        """
        Send an email using an HTML template with variable substitution.

        Args:
            to: Recipient email(s)
            subject: Email subject
            template_html: HTML template with {variable} placeholders
            variables: Dict of variable replacements
            reply_to: Reply-to address

        Returns:
            Dict with id and success status
        """
        html = template_html
        if variables:
            for key, value in variables.items():
                html = html.replace(f"{{{key}}}", str(value))

        return self.send(
            to=to,
            subject=subject,
            html=html,
            reply_to=reply_to,
        )

    # --- checks -------------------------------------------------------------

    @staticmethod
    def _need(value: Any, name: str) -> Any:
        """A required argument, refused locally when empty."""
        if value is None or (isinstance(value, str) and not value.strip()):
            raise ValueError(f"`{name}` is required.")
        return value

    @classmethod
    def _seg(cls, value: Any, name: str) -> str:
        """One path segment — an id, or a contact's email — percent-encoded.
        `@` stays as is, the form the API documents for an email in the path."""
        if not isinstance(value, str):
            raise ValueError(f"`{name}` must be a string; got {value!r}.")
        return quote(cls._need(value, name).strip(), safe="@")

    @staticmethod
    def _page(limit: Optional[int], after: Optional[str],
              before: Optional[str]) -> Dict[str, Any]:
        """Cursor pagination params: `limit` 1–100, `after` or `before`."""
        if limit is not None and (isinstance(limit, bool) or not isinstance(limit, int)
                                  or not 1 <= limit <= MAX_PAGE_SIZE):
            raise ValueError(
                f"`limit` must be an integer between 1 and {MAX_PAGE_SIZE}; got {limit!r}.")
        if after and before:
            raise ValueError("Pass `after` or `before`, not both.")
        params = {"limit": limit, "after": after, "before": before}
        return {k: v for k, v in params.items() if v not in (None, "")}

    # --- transport ----------------------------------------------------------

    def _pace(self) -> None:
        """At most one call per `MIN_INTERVAL_S` from this client."""
        if self._last_call is not None:
            wait = MIN_INTERVAL_S - (time.monotonic() - self._last_call)
            if wait > 0:
                time.sleep(wait)
        self._last_call = time.monotonic()

    @staticmethod
    def _retry_wait(resp: Any, attempt: int) -> Optional[float]:
        """Seconds to wait before retrying a read; `None` = do not retry."""
        if resp.status_code == 429:
            headers = getattr(resp, "headers", None) or {}
            raw = headers.get("retry-after") or headers.get("Retry-After") or 1
            try:
                wait = max(0.0, float(raw))
            except (TypeError, ValueError):
                return None
            return wait if wait <= RATE_LIMIT_MAX_WAIT else None
        return float(2 ** attempt)

    def _request(self, method: str, path: str, *,
                 params: Optional[Dict[str, Any]] = None, json: Any = None) -> Any:
        retryable = method == "GET"
        last = None
        for attempt in range(MAX_ATTEMPTS):
            self._pace()
            last = self.session.request(
                method, f"{self.BASE_URL}{path}", params=params or None, json=json,
                timeout=HTTP_TIMEOUT, allow_redirects=False)
            refuse_redirect(last)
            if (last.status_code not in RETRY_STATUSES or not retryable
                    or attempt == MAX_ATTEMPTS - 1):
                break
            wait = self._retry_wait(last, attempt)
            if wait is None:
                break
            time.sleep(wait)
        raise_for_upstream(last, service="resend")
        return last.json() if last.content else {}

    def _get(self, path: str, params: Optional[Dict[str, Any]] = None) -> Any:
        return self._request("GET", path, params=params)

    def _post(self, path: str, body: Optional[Dict[str, Any]]) -> Any:
        return self._request("POST", path, json=body)

    def _patch(self, path: str, body: Dict[str, Any]) -> Any:
        return self._request("PATCH", path, json=body)

    def _delete(self, path: str) -> Any:
        return self._request("DELETE", path)


__all__ = [
    "ResendClient", "send_email", "BASE_URL", "HTTP_TIMEOUT", "MAX_ATTEMPTS",
    "MAX_PAGE_SIZE", "MAX_WALK_PAGES", "MIN_INTERVAL_S", "RATE_LIMIT_MAX_WAIT",
    "RETRY_STATUSES",
]
