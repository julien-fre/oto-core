"""LinkedIn Ads auth — LinkedIn's 3-legged OAuth 2.0 (authorization code).

A person signs in to LinkedIn and consents, once, to the application reading the
ad accounts on which they hold a role (Campaign Manager: VIEWER is enough to read).
The application is the one of the publisher that consumes the lib, created on the
LinkedIn Developer Portal with the Advertising API product: its `client_id` and
`client_secret` are passed as arguments, never read here.

**Read-only by its scopes**: only `r_ads` (ad accounts, campaign groups, campaigns,
creatives) and `r_ads_reporting` (adAnalytics) are asked — never `rw_ads`. A token
minted here cannot change an ad account, whatever the code that holds it does.
⚠️ Changing `SCOPES` invalidates every token already issued (LinkedIn voids the
previous tokens when another scope set is requested): the person must reconnect.

Lifetimes (LinkedIn documentation): the access token lives 60 days. A refresh token
(365 days, NOT extended by a refresh: the new access token lives 60 days, the refresh
token keeps its initial end) is only issued to applications enabled for
programmatic refresh tokens; without one, `Grant.refresh_token` is empty and the
person reconnects when the access token expires.

Same guards as the lib's other auth modules: secrets go in **`data=`**, never in
`params=`, no redirect is followed, and no `raise_for_status()` (its message embeds
the URL).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional
from urllib.parse import urlencode

import requests

from ..common.credentials import require
from ..http.client import refuse_redirect

_HTTP_TIMEOUT = (10, 30)  # (connect, read)
AUTHORIZE_URL = "https://www.linkedin.com/oauth/v2/authorization"
TOKEN_URL = "https://www.linkedin.com/oauth/v2/accessToken"
#: Read-only on purpose: `rw_ads` is never asked.
SCOPES = ("r_ads", "r_ads_reporting")
#: Lifetime announced by LinkedIn for every access token, when a response gives none.
DEFAULT_EXPIRES_IN = 60 * 24 * 3600

# OAuth errors meaning "the authorization is dead, sign in again".
_GRANT_MORT = ("invalid_grant",)
_GRANT_MORT_TEXTE = ("invalid, expired or revoked", "expired", "revoked")


class LinkedInAdsAuthError(ValueError):
    """Refusal by LinkedIn's authorization server. Carries a `status_code` (the
    `UpstreamHTTPError` contract) and the OAuth `code` when readable."""

    def __init__(self, message: str, *, status_code: int = 401, code: Optional[str] = None):
        super().__init__(message)
        self.status_code = status_code
        self.code = code


class LinkedInAdsGrantExpired(LinkedInAdsAuthError):
    """The person's authorization is no longer valid (revoked, expired): they must
    sign in again. The application's configuration is not at fault."""


@dataclass(frozen=True)
class Grant:
    """What a token response carries. `refresh_token` is empty when the application
    is not enabled for refresh tokens; `refresh_token_expires_in` is then 0."""

    access_token: str
    expires_in: int
    refresh_token: str
    refresh_token_expires_in: int
    scope: str


def authorize_url(client_id: str, redirect_uri: str, state: str) -> str:
    """The URL of LinkedIn's consent page. `redirect_uri` must be declared, byte for
    byte, among the application's Authorized redirect URLs."""
    params = {
        "response_type": "code",
        "client_id": require(client_id, "LINKEDIN_ADS_CLIENT_ID"),
        "redirect_uri": require(redirect_uri, "redirect_uri"),
        "state": require(state, "state"),
        "scope": " ".join(SCOPES),
    }
    return f"{AUTHORIZE_URL}?{urlencode(params)}"


def _token(data: dict, *, keep_refresh: str = "") -> Grant:
    # Never follow a redirect: a 307/308 would replay the body — client secret, code
    # or refresh token — to the host named by `Location`.
    resp = requests.post(TOKEN_URL, data=data, timeout=_HTTP_TIMEOUT,
                         allow_redirects=False)
    refuse_redirect(resp)
    try:
        payload = resp.json()
    except ValueError:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    if resp.status_code >= 400 or "access_token" not in payload:
        error = str(payload.get("error") or "")
        description = str(payload.get("error_description") or payload.get("message") or "")
        detail = description.splitlines()[0] if description else (error or "response without a token")
        status = resp.status_code if resp.status_code >= 400 else 401
        mort = error in _GRANT_MORT or (
            keep_refresh and any(t in description.lower() for t in _GRANT_MORT_TEXTE))
        cls = LinkedInAdsGrantExpired if mort else LinkedInAdsAuthError
        raise cls(f"LinkedIn refused the token request (HTTP {resp.status_code}): {detail}",
                  status_code=status, code=error or None)
    refresh = str(payload.get("refresh_token") or keep_refresh or "")
    return Grant(access_token=str(payload["access_token"]),
                 expires_in=int(payload.get("expires_in") or DEFAULT_EXPIRES_IN),
                 refresh_token=refresh,
                 refresh_token_expires_in=int(payload.get("refresh_token_expires_in") or 0)
                 if refresh else 0,
                 scope=str(payload.get("scope") or ""))


def exchange_code(client_id: str, client_secret: str, code: str, redirect_uri: str) -> Grant:
    """The code brought back by the browser (valid 30 minutes) in exchange for a
    `Grant`. `redirect_uri` is the one of the `authorize_url` call."""
    return _token({  # ⚠️ `data=`, JAMAIS `params=`
        "grant_type": "authorization_code",
        "code": require(code, "code"),
        "client_id": require(client_id, "LINKEDIN_ADS_CLIENT_ID"),
        "client_secret": require(client_secret, "LINKEDIN_ADS_CLIENT_SECRET"),
        "redirect_uri": require(redirect_uri, "redirect_uri"),
    })


def refresh(client_id: str, client_secret: str, refresh_token: str) -> Grant:
    """A fresh access token (60 days) from the refresh token. The refresh token keeps
    its initial end of life; when LinkedIn returns one, it replaces the one passed in."""
    token = require(refresh_token, "LINKEDIN_ADS_REFRESH_TOKEN")
    return _token({  # ⚠️ `data=`, JAMAIS `params=`
        "grant_type": "refresh_token",
        "refresh_token": token,
        "client_id": require(client_id, "LINKEDIN_ADS_CLIENT_ID"),
        "client_secret": require(client_secret, "LINKEDIN_ADS_CLIENT_SECRET"),
    }, keep_refresh=token)
