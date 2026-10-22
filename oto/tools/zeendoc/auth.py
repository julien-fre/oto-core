"""Zeendoc session — a user account opens a session, a cookie carries it.

`POST https://armoires.zeendoc.com/{url_client}/api/v4/login` with the account's
`{login, password}` in a JSON body answers `{cookie: "ZeenDoc=<id>",
cookieDuration: "<seconds>s"}`. That one cookie authenticates the REST API and
the application pages that serve a document's text and files alike.

- The password travels in the JSON body, never in a query string, and no
  `raise_for_status()` is called here: an exception message must never carry a
  credential.
- A refused login answers 401 `{"message": "Authentication failed."}`, yet may
  still set a cookie: only the status and the body say whether it succeeded.
- The cache is process-wide, keyed by a hash of the credential: a server builds
  one client per call, so a cache held by the instance would never be reused.
"""
from __future__ import annotations

import hashlib
import re
import time
from typing import Optional

import requests

from ..common import UpstreamHTTPError
from ..http.client import refuse_redirect

_HTTP_TIMEOUT = (10, 30)

# A session is renewed this long before the end the login announced.
_MARGIN_S = 300
# Used when the login does not say how long the session lasts.
_DEFAULT_DURATION_S = 3600

# {cred_key: (cookie value, expires_at_epoch)}
_SESSIONS: dict[str, tuple[str, float]] = {}

_COOKIE = re.compile(r"^ZeenDoc=([A-Za-z0-9,-]+)$")
_DURATION = re.compile(r"^(\d+)s?$")


class ZeendocAuthError(UpstreamHTTPError):
    """Zeendoc refused the login and password.

    Always `status_code == 401`, so that a consumer routes it as a credential
    refusal, not as bad input."""

    def __init__(self, error: str):
        super().__init__(401, {"error": error}, service="zeendoc")


def cred_key(base_url: str, login: str, password: str) -> str:
    """Opaque, stable id of a credential — never a secret in clear."""
    return hashlib.sha256(f"{base_url}|{login}|{password}".encode()).hexdigest()


def get_session_cookie(base_url: str, *, login: str, password: str,
                       key: Optional[str] = None) -> str:
    """The `ZeenDoc` session cookie of this account, logging in only when needed.

    `base_url` is the cabinet's root, `https://armoires.zeendoc.com/{url_client}`."""
    k = key or cred_key(base_url, login, password)
    cached = _SESSIONS.get(k)
    if cached and cached[1] > time.time() + _MARGIN_S:
        return cached[0]

    resp = requests.post(
        f"{base_url}/api/v4/login",
        json={"login": login, "password": password},  # body, never params=
        headers={"Accept": "application/json"},
        timeout=_HTTP_TIMEOUT,
        allow_redirects=False,  # a 307/308 would replay the password to another host
    )
    refuse_redirect(resp)

    if resp.status_code == 401:
        raise ZeendocAuthError("login or password refused")
    if resp.status_code >= 400:
        # The raw body is never echoed: only the status is kept.
        raise UpstreamHTTPError(resp.status_code, {"error": "login endpoint error"},
                                service="zeendoc")

    try:
        payload = resp.json()
    except ValueError:
        payload = None
    match = _COOKIE.match(payload.get("cookie") or "") if isinstance(payload, dict) else None
    if not match:
        raise UpstreamHTTPError(502, {"error": "no session cookie in login response"},
                                service="zeendoc")

    duration = _DURATION.match(str(payload.get("cookieDuration") or ""))
    lifetime = int(duration.group(1)) if duration else _DEFAULT_DURATION_S
    _SESSIONS[k] = (match.group(1), time.time() + lifetime)
    return match.group(1)


def invalidate(key: str) -> None:
    """Forget the cached session of this credential (called when Zeendoc says it
    is no longer open)."""
    _SESSIONS.pop(key, None)
