"""Pipecorn API client — waterfall contact enrichment (professional email, mobile phone,
personal email) and the account's credit balance.

Authenticated by an API key in **`X-API-KEY`** (Pipecorn → Settings → API keys). A
test key (`pc_test_…`, and the public `pc_test_demo`) answers every route with sample
data and spends nothing; responses carry `Pipecorn-Mode: test`. One method = one
endpoint; responses are returned as-is.

What the caller needs to know, and cannot guess:

- **Two hosts, two ways.** The SYNCHRONOUS enrichment (`enrich_contact`) is served on
  `https://api.pipecorn.com/v2` only. The same path on the main host
  (`https://app.pipecorn.com/api/v2`) is the ASYNCHRONOUS one (`submit_enrichment`):
  it answers `200` with `status: "pending"` and an `enrichment_id`, and the result is
  read later on `GET /contacts/{id}` (`get_enrichment`). Every other route (credits,
  account) lives on the main host. Hence `SYNC_URL` and `BASE_URL`, never swapped.
- **What a lookup needs.** `phone` and `personal_email` need `linkedin_url`; `email`
  takes `linkedin_url`, or `firstname` + `lastname` + `domain` or `company_name`.
  Checked here before the call (Pipecorn answers 422, before any credit is spent).
- **What it costs** (Pipecorn credits, per result FOUND, nothing on a miss): 3 per
  professional email, 9 per personal email, 30 per phone — and a phone only bills
  when a MOBILE (`mobile` or `fixed_or_mobile`) is found. The response carries no
  cost field: `credits_spent` derives it from what the answer holds.
- **Personal email** needs the account owner's consent in Pipecorn's settings (422
  otherwise).
- **Credit errors.** 402 `insufficient_credits` (balance too low, nothing spent), 403
  `workspace_limit_exceeded` (the member's weekly cap). Credit-spending routes are
  exempt from rate limits.

Requires: requests
"""
from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Optional

import requests

from ..common import raise_for_upstream
from ..common.credentials import require
from ..http.client import refuse_redirect

BASE_URL = "https://app.pipecorn.com/api/v2"
SYNC_URL = "https://api.pipecorn.com/v2"

# (connect, read). Pipecorn runs its own provider waterfall during the sync call;
# a caller with a tighter budget passes its own `timeout`.
HTTP_TIMEOUT = (10, 60)

ENRICHMENT_TYPES = ("email", "phone", "personal_email")
PHONE_TYPES = ("all", "mobile")
#: Pipecorn credits per result found (its published grid, docs "Credits vs limits").
CREDITS = {"email": 3, "personal_email": 9, "phone": 30}
#: Line types a phone is billed on — and that `phone_type=["mobile"]` keeps.
MOBILE_TYPES = frozenset({"mobile", "fixed_or_mobile"})

_COUNTRY = re.compile(r"^[A-Z]{2}$")
# An enrichment id lands in the path: a UUID, so that no value can reshape the URL.
_ENRICHMENT_ID = re.compile(r"^[0-9a-fA-F-]{36}$")


def credits_spent(result: Any, asked: Optional[Iterable[str]] = None) -> int:
    """The Pipecorn credits one finished enrichment cost (the synchronous answer, or
    the `finished` result of an asynchronous one): 3 for an email,
    9 for a personal email, 30 when a mobile is among the phones; 0 on a miss.
    `asked` (the call's `enrichment_type`) bounds it: a field the call did not ask
    for is never counted, whatever the answer holds. A number the workspace
    suppressed (`"Contacts not shared"`) is not counted."""
    if not isinstance(result, dict):
        return 0
    kinds = set(ENRICHMENT_TYPES if asked is None else asked)
    spent = 0
    if "email" in kinds and result.get("email"):
        spent += CREDITS["email"]
    if "personal_email" in kinds and result.get("personal_email"):
        spent += CREDITS["personal_email"]
    details = result.get("phone_details") or []
    if "phone" in kinds and any(
            isinstance(d, dict) and d.get("type") in MOBILE_TYPES
            and str(d.get("number") or "").startswith("+") for d in details):
        spent += CREDITS["phone"]
    return spent


class PipecornClient:
    """Pipecorn API v2: waterfall enrichment (synchronous, or submitted then polled)
    and the account's balance."""

    BASE_URL = BASE_URL
    SYNC_URL = SYNC_URL

    def __init__(self, api_key: Optional[str] = None):
        """
        Args:
            api_key: Pipecorn API key (Settings → API keys), sent as `X-API-KEY`.
        """
        self.api_key = require(api_key, "PIPECORN_API_KEY").strip()
        self.session = requests.Session()
        self.session.headers.update({"X-API-KEY": self.api_key,
                                     "Accept": "application/json"})

    # --- transport ----------------------------------------------------------

    def _call(self, method: str, url: str, *, json: Optional[dict] = None,
              headers: Optional[dict] = None, timeout=HTTP_TIMEOUT) -> Any:
        """One request, never retried (an enrichment spends credits) and never
        redirected (the key is in a custom header, which `requests` would forward)."""
        resp = self.session.request(method, url, json=json, headers=headers,
                                    timeout=timeout, allow_redirects=False)
        refuse_redirect(resp)
        raise_for_upstream(resp, service="pipecorn")
        return resp.json() if resp.content else {}

    # --- account ------------------------------------------------------------

    def probe(self) -> Any:
        """Check that the key authenticates: reads the balance, free."""
        return self.get_credits()

    def get_credits(self) -> Dict[str, Any]:
        """`GET /credits` — `credits.enrichment` is the spendable balance; the other
        `credits.*` are the plan's remaining extraction quotas, `limits.*` their
        ceilings. Free."""
        return self._call("GET", f"{self.BASE_URL}/credits")

    def get_account_info(self) -> Dict[str, Any]:
        """`GET /account` — the plan, the email behind the key, and whether the
        LinkedIn / Sales Navigator sessions are valid. Free."""
        return self._call("GET", f"{self.BASE_URL}/account")

    # --- enrichment ---------------------------------------------------------

    def enrich_contact(self, enrichment_type: List[str], *,
                       linkedin_url: Optional[str] = None,
                       firstname: Optional[str] = None,
                       lastname: Optional[str] = None,
                       domain: Optional[str] = None,
                       company_name: Optional[str] = None,
                       phone_type: Optional[str] = None,
                       phone_country_codes: Optional[List[str]] = None,
                       custom: Optional[Dict[str, Any]] = None,
                       idempotency_key: Optional[str] = None,
                       timeout=HTTP_TIMEOUT) -> Dict[str, Any]:
        """`POST https://api.pipecorn.com/v2/contacts/single_enrich` — synchronous
        waterfall enrichment of ONE contact; the answer holds the result.

        Args:
            enrichment_type: any of `email`, `phone`, `personal_email`.
            linkedin_url: the profile URL — required for `phone` and
                `personal_email`, and enough on its own for `email`.
            firstname, lastname, domain, company_name: for `email` without a
                LinkedIn URL (both names, and a domain or a company name).
            phone_type: `all` (default) or `mobile` — with `mobile`, Pipecorn keeps
                looking until a provider has a mobile, and drops landlines.
            phone_country_codes: ISO alpha-2 codes (`FR`, `US`) to keep phones to.
            custom: passed through and returned under `custom`.
            idempotency_key: a retry with the same key and body returns the stored
                answer instead of spending again (kept 24 h).
            timeout: `(connect, read)` seconds, or one number.

        Returns: `{enrichment_id, first_name, last_name, linkedin_profile_url,
        status: "finished", email, email_status, phones, phone_details: [{number,
        type}], phone_status, personal_email, personal_email_status, custom}` —
        only the fields of the asked types. A miss is a 200 with empty fields
        (`phone_status: "not_found"`); `credits_spent` reads what it cost.
        """
        body = self._body(enrichment_type, linkedin_url, firstname, lastname, domain,
                          company_name, phone_type, phone_country_codes, custom)
        headers = {"Idempotency-Key": idempotency_key} if idempotency_key else None
        return self._call("POST", f"{self.SYNC_URL}/contacts/single_enrich", json=body,
                          headers=headers, timeout=timeout)

    def submit_enrichment(self, enrichment_type: List[str], *,
                          linkedin_url: Optional[str] = None,
                          firstname: Optional[str] = None,
                          lastname: Optional[str] = None,
                          domain: Optional[str] = None,
                          company_name: Optional[str] = None,
                          phone_type: Optional[str] = None,
                          phone_country_codes: Optional[List[str]] = None,
                          custom: Optional[Dict[str, Any]] = None,
                          idempotency_key: Optional[str] = None) -> Dict[str, Any]:
        """`POST https://app.pipecorn.com/api/v2/contacts/single_enrich` — ASYNCHRONOUS
        waterfall enrichment of ONE contact: queued, answered at once; the result is
        read later with `get_enrichment`. Same arguments as `enrich_contact`; no
        webhook (the result is polled). Credits are checked before queuing (402 / 403,
        nothing queued) and spent when the enrichment finishes, on what it found.

        Returns: `{enrichment_id, first_name, last_name, status: "pending",
        status_url}`.
        """
        body = self._body(enrichment_type, linkedin_url, firstname, lastname, domain,
                          company_name, phone_type, phone_country_codes, custom)
        headers = {"Idempotency-Key": idempotency_key} if idempotency_key else None
        return self._call("POST", f"{self.BASE_URL}/contacts/single_enrich", json=body,
                          headers=headers)

    def get_enrichment(self, enrichment_id: str) -> Dict[str, Any]:
        """`GET /contacts/{enrichment_id}` — the result of an asynchronous enrichment.
        Free, and exempt from the rate limit (poll it, backing off from 2 s to 30 s).

        Returns: `status` `pending` (still running), `finished` (every asked type done,
        found or not: `email`, `email_status`, `phone` — a list here, not `phones` —,
        `phone_details`, `personal_email`, …) or `failed` (credits ran out while it
        ran: `code` is `insufficient_credits` or `workspace_limit_exceeded`).
        """
        ident = enrichment_id.strip() if isinstance(enrichment_id, str) else ""
        if not _ENRICHMENT_ID.match(ident):
            raise ValueError("`enrichment_id` must be the id an enrichment returned "
                             f"(a UUID); got {enrichment_id!r}.")
        return self._call("GET", f"{self.BASE_URL}/contacts/{ident}")

    def _body(self, enrichment_type, linkedin_url, firstname, lastname, domain,
              company_name, phone_type, phone_country_codes, custom) -> Dict[str, Any]:
        """The enrichment body, checked: what Pipecorn would refuse with a 422 is
        refused here, before any call."""
        kinds = self._kinds(enrichment_type)
        if ("phone" in kinds or "personal_email" in kinds) and not linkedin_url:
            raise ValueError("`linkedin_url` is required for a phone or a personal email.")
        if "email" in kinds and not linkedin_url:
            if not (firstname and lastname):
                raise ValueError("An email without `linkedin_url` needs `firstname` and "
                                 "`lastname`.")
            if not (domain or company_name):
                raise ValueError("An email without `linkedin_url` needs `domain` or "
                                 "`company_name`.")
        body: Dict[str, Any] = {"enrichment_type": kinds}
        for name, value in (("linkedin_url", linkedin_url), ("firstname", firstname),
                            ("lastname", lastname), ("domain", domain),
                            ("company_name", company_name)):
            if value:
                body[name] = value.strip()
        if phone_type is not None:
            if phone_type not in PHONE_TYPES:
                raise ValueError(f"`phone_type` must be one of {', '.join(PHONE_TYPES)}; "
                                 f"got {phone_type!r}.")
            body["phone_type"] = [phone_type]
        if phone_country_codes is not None:
            codes = [str(c).strip().upper() for c in phone_country_codes]
            if not codes or not all(_COUNTRY.match(c) for c in codes):
                raise ValueError("`phone_country_codes` must be a non-empty list of ISO "
                                 f"alpha-2 codes (FR, US…); got {phone_country_codes!r}.")
            body["phone_country_codes"] = codes
        if custom is not None:
            if not isinstance(custom, dict):
                raise ValueError("`custom` must be an object.")
            body["custom"] = custom
        return body

    @staticmethod
    def _kinds(enrichment_type: Any) -> List[str]:
        if isinstance(enrichment_type, str):
            enrichment_type = [enrichment_type]
        if not isinstance(enrichment_type, (list, tuple)) or not enrichment_type:
            raise ValueError("`enrichment_type` must be a non-empty list of "
                             f"{', '.join(ENRICHMENT_TYPES)}.")
        kinds = list(dict.fromkeys(enrichment_type))
        unknown = [k for k in kinds if k not in ENRICHMENT_TYPES]
        if unknown:
            raise ValueError(f"Unknown `enrichment_type` {unknown}: accepted "
                             f"{', '.join(ENRICHMENT_TYPES)}.")
        return kinds
