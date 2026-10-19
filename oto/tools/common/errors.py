"""Typed connector errors.

`UpstreamHTTPError` distinguishes a **refusal by the third-party API** (HTTP status >= 400:
rejected input, invalid credential, missing target, rate limit…) from an **internal bug**
in the code. The `status_code` lets consumers (MCP adapter, error tracking)
route a 4xx as a *handled connector error* — traced in the call backlog,
returned cleanly to the agent — rather than as a backend defect to alert on.

The error also says WHICH request was answered, so a caller can tell a refusal from an
ambiguous send without reading the message text:

- `status_code`, `body` (parsed JSON or raw text), `service`;
- `method` and `url` of the request, when known. The URL is sanitized (`sanitize_url`):
  scheme, host and path only — no query, fragment nor userinfo, where API keys often travel;
- `retry_after`: the `Retry-After` header of a 429, in seconds, when readable
  (`retry_after_seconds`), otherwise `None`.

An exception raised BEFORE any HTTP call (argument validation, missing credential) is never
an `UpstreamHTTPError`: nothing was sent.

`raise_for_upstream(resp, service=...)` replaces the duplicated block
`if resp.status_code >= 400: parse body; raise Exception(...)` found in every
client; `UpstreamHTTPError.from_response(resp, ...)` builds the same error when a client
shapes its own `body`. Agnostic to `requests`/`httpx` for the status and body (same
`.status_code` / `.json()` / `.text` / `.headers`); `method` and `url` are read from
`resp.request` when it carries them as strings (`requests.PreparedRequest`).
"""
from __future__ import annotations

import math
from typing import Any, Optional
from urllib.parse import urlsplit, urlunsplit

_UNSET: Any = object()


def sanitize_url(url: Optional[str]) -> Optional[str]:
    """`url` reduced to scheme, host (and port) and path: query, fragment and userinfo removed.

    An API key often travels as a query parameter (`?key=…`) or as userinfo
    (`https://key@host/`): neither may reach an error message, a log or a trace.
    `None` (or an empty string) gives `None`."""
    if not url:
        return None
    parts = urlsplit(url)
    host = parts.netloc.rpartition("@")[2]
    return urlunsplit((parts.scheme, host, parts.path, "", ""))


def retry_after_seconds(resp: Any) -> Optional[float]:
    """`Retry-After` of a response in seconds (delta-seconds form), `None` when absent or
    unreadable. A negative value counts as `0`; a non-finite one is unreadable.

    The HTTP-date form is not read here: it gives `None`."""
    raw = (getattr(resp, "headers", None) or {}).get("Retry-After")
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    return max(0.0, value) if math.isfinite(value) else None


def _request_line(resp: Any) -> tuple[Optional[str], Optional[str]]:
    """`(method, url)` of the request that `resp` answers, when it carries them as strings."""
    try:
        request = getattr(resp, "request", None)
    except RuntimeError:  # httpx: a response built without a request
        return None, None
    method = getattr(request, "method", None)
    url = getattr(request, "url", None)
    return (method if isinstance(method, str) else None,
            url if isinstance(url, str) else None)


def _parsed_body(resp: Any) -> Any:
    try:
        return resp.json()
    except Exception:
        return resp.text


class UpstreamHTTPError(Exception):
    """A third-party API answered with an error (status >= 400).

    `status_code` = upstream HTTP code, `body` = parsed body (dict) or raw text,
    `service` = connector name (prefixes the message, e.g. « folk HTTP 422: … »),
    `method` / `url` = the request answered (URL sanitized, `None` if unknown),
    `retry_after` = seconds the upstream asks to wait (`None` if not given).
    """

    def __init__(self, status_code: int, body: Any = None, *, service: Optional[str] = None,
                 method: Optional[str] = None, url: Optional[str] = None,
                 retry_after: Optional[float] = None):
        self.status_code = status_code
        self.body = body
        self.service = service
        self.method = method.upper() if method else None
        self.url = sanitize_url(url)
        self.retry_after = retry_after
        prefix = f"{service} " if service else ""
        super().__init__(f"{prefix}HTTP {status_code}: {body}")

    @classmethod
    def from_response(cls, resp: Any, *, service: Optional[str] = None, body: Any = _UNSET,
                      method: Optional[str] = None, url: Optional[str] = None) -> "UpstreamHTTPError":
        """The error for `resp`. `body` defaults to the parsed body (JSON, else raw text);
        `method` / `url` default to those of `resp.request`; `retry_after` is read on a 429."""
        req_method, req_url = _request_line(resp)
        return cls(
            resp.status_code,
            _parsed_body(resp) if body is _UNSET else body,
            service=service,
            method=method or req_method,
            url=url or req_url,
            retry_after=retry_after_seconds(resp) if resp.status_code == 429 else None,
        )

    @property
    def is_client_error(self) -> bool:
        """4xx — the request was bad (our input / our credentials)."""
        return 400 <= self.status_code < 500

    @property
    def is_server_error(self) -> bool:
        """5xx — the upstream is broken."""
        return 500 <= self.status_code < 600


def raise_for_upstream(resp: Any, *, service: Optional[str] = None) -> None:
    """Raise `UpstreamHTTPError` if `resp.status_code >= 400`, otherwise no-op.

    Parses the body as JSON, falling back to raw text. Compatible with `requests.Response`
    and `httpx.Response`.
    """
    if resp.status_code >= 400:
        raise UpstreamHTTPError.from_response(resp, service=service)
