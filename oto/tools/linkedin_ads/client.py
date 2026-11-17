"""LinkedIn Ads client — the Advertising API (Marketing API), READ-ONLY.

Qualification (docs/conception/concevoir-un-connecteur.md, step 1):

- **Who holds the access**: a person. Their LinkedIn consent (3-legged OAuth, `auth`)
  yields a token that reads the ad accounts on which THEY hold a Campaign Manager
  role (VIEWER is enough). The application is the consumer's, created on the
  LinkedIn Developer Portal with the Advertising API product (approval by LinkedIn).
- **Authentication**: `Authorization: Bearer <access token>`, plus two headers on
  every call: `LinkedIn-Version: YYYYMM` (versioned API, each version is supported
  about a year) and `X-Restli-Protocol-Version: 2.0.0`.
- **What a key allows**: the scopes `r_ads` + `r_ads_reporting` only — read-only by
  construction, no `rw_ads`. Without a role on an account, a read answers 403, and
  adAnalytics answers an EMPTY list (not a refusal).
- **Cost**: free. **Engages**: nothing — every method here is a GET.
- **Limits**: per-application and per-member daily call limits (reset at midnight
  UTC, not published: shown in the application's Analytics tab), 429 beyond;
  adAnalytics also throttles at 45 million metric values per 5 minutes per
  application (metrics requested x rows returned) and answers at most 15,000 rows,
  without pagination. No retry here: a 429 is the caller's to wait out.
- **Not described in the format** (`connectors/clients.yaml`): the Rest.li 2.0 query
  syntax is composed at call time — `List(...)` with URN-encoded elements, nested
  records for `search` and `dateRange` — and a creative's URN goes encoded in the path.

Scope: ad accounts and the caller's role on each, campaign groups, campaigns (with
their budget, bid and targeting), creatives, and adAnalytics (analytics finder for one
pivot, statistics finder for two or three). Not here: any write; query tunneling (a
POST — facets are capped instead, `MAX_FACET_VALUES`); the attributed-revenue finder;
resolving targeting URNs into names; lead forms; audiences.

One method = one endpoint; responses are returned as LinkedIn sends them, the only
shaping being a search page reduced to `{elements, next_page_token}`.

Requires: requests
"""
from __future__ import annotations

import datetime as _dt
import re
from typing import Any, Iterable, Optional
from urllib.parse import quote

import requests

from ..common import raise_for_upstream
from ..common.credentials import require
from ..http.client import refuse_redirect

HTTP_TIMEOUT = (10, 30)  # (connect, read) — never an unbounded wait
API_BASE = "https://api.linkedin.com/rest"
#: Marketing API version sent in `LinkedIn-Version` (supported about a year).
LINKEDIN_VERSION = "202610"
SERVICE = "linkedin_ads"

ACCOUNT_STATUSES = ("ACTIVE", "CANCELED", "DRAFT", "PENDING_DELETION", "REMOVED")
CAMPAIGN_GROUP_STATUSES = ("ACTIVE", "ARCHIVED", "CANCELED", "DRAFT", "PAUSED",
                           "PENDING_DELETION", "REMOVED")
CAMPAIGN_STATUSES = ("ACTIVE", "PAUSED", "ARCHIVED", "COMPLETED", "CANCELED", "DRAFT",
                     "PENDING_DELETION", "REMOVED")
CAMPAIGN_TYPES = ("TEXT_AD", "SPONSORED_UPDATES", "SPONSORED_INMAILS", "DYNAMIC")
CREATIVE_STATUSES = ("ACTIVE", "PAUSED", "DRAFT", "ARCHIVED", "CANCELED",
                     "PENDING_DELETION", "REMOVED")
#: What a search returns when the caller names no status: everything but deleted.
DEFAULT_CAMPAIGN_GROUP_STATUSES = ("ACTIVE", "PAUSED", "ARCHIVED", "DRAFT")
DEFAULT_CAMPAIGN_STATUSES = ("ACTIVE", "PAUSED", "ARCHIVED", "COMPLETED", "DRAFT")

TIME_GRANULARITIES = ("ALL", "DAILY", "MONTHLY", "YEARLY")
PIVOTS = ("COMPANY", "ACCOUNT", "SHARE", "CAMPAIGN", "CREATIVE", "CAMPAIGN_GROUP",
          "CONVERSION", "CONVERSATION_NODE", "CONVERSATION_NODE_OPTION_INDEX",
          "SERVING_LOCATION", "CARD_INDEX", "MEMBER_COMPANY_SIZE", "MEMBER_INDUSTRY",
          "MEMBER_SENIORITY", "MEMBER_JOB_TITLE", "MEMBER_JOB_FUNCTION",
          "MEMBER_COUNTRY_V2", "MEMBER_REGION_V2", "MEMBER_COMPANY",
          "PLACEMENT_NAME", "IMPRESSION_DEVICE_TYPE", "OBJECTIVE_TYPE", "EVENT_STAGE")
#: Pivots the statistics finder (2-3 pivots) refuses: professional demographics.
DEMOGRAPHIC_PIVOTS = tuple(p for p in PIVOTS if p.startswith("MEMBER_"))
#: Metrics returned when the caller names none (LinkedIn returns only impressions and
#: clicks without `fields`).
DEFAULT_METRICS = ("impressions", "clicks", "costInLocalCurrency", "landingPageClicks",
                   "totalEngagements", "externalWebsiteConversions", "oneClickLeads",
                   "videoViews")
#: LinkedIn's cap on metrics per adAnalytics call.
MAX_METRICS = 20
MAX_PIVOTS = 3
#: URNs per facet: bounds the URL (beyond, LinkedIn wants query tunneling, a POST).
MAX_FACET_VALUES = 20
MAX_PAGE_SIZE = 1000
MAX_CREATIVE_PAGE_SIZE = 100

_DIGITS = re.compile(r"^\d{1,20}$")
_METRIC = re.compile(r"^[A-Za-z][A-Za-z0-9]{0,63}$")
_DAY = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_URN_KIND = {
    "account": "sponsoredAccount",
    "campaign_group": "sponsoredCampaignGroup",
    "campaign": "sponsoredCampaign",
    "creative": "sponsoredCreative",
}


# --- Rest.li 2.0 encoding ----------------------------------------------------------

def _enc(value: str) -> str:
    """One Rest.li leaf value: every reserved character percent-encoded (`:` of a URN
    included), so that only the structure's own `( ) , :` stay literal."""
    return quote(str(value), safe="")


def restli_list(values: Iterable[str]) -> str:
    """`List(v1,v2)` — each element encoded."""
    return "List(" + ",".join(_enc(v) for v in values) + ")"


def restli_date(day: _dt.date) -> str:
    return f"(year:{day.year},month:{day.month},day:{day.day})"


def _query(pairs: list[tuple[str, Optional[str]]]) -> str:
    """The query string, values ALREADY Rest.li-encoded: `requests` must not encode the
    structure again (a `%28` instead of `(` is a different request to LinkedIn)."""
    return "&".join(f"{k}={v}" for k, v in pairs if v not in (None, ""))


# --- argument checks -----------------------------------------------------------------

def entity_id(value: Any, kind: str) -> str:
    """An id of `kind` as digits — accepts the digits or the full URN
    (`urn:li:sponsoredCampaign:123`). Nothing else goes into a path or a query."""
    text = str(value).strip() if value is not None else ""
    prefix = f"urn:li:{_URN_KIND[kind]}:"
    if text.startswith(prefix):
        text = text[len(prefix):]
    if not _DIGITS.match(text):
        raise ValueError(f"`{kind}_id` must be digits or {prefix}<digits>; got {value!r}.")
    return text


def urn(value: Any, kind: str) -> str:
    return f"urn:li:{_URN_KIND[kind]}:{entity_id(value, kind)}"


def _choices(name: str, values: Optional[Iterable[str]], allowed: tuple) -> list[str]:
    out = []
    for v in values or ():
        if v not in allowed:
            raise ValueError(f"`{name}` invalid: {v!r}. Accepted values: {', '.join(allowed)}.")
        out.append(v)
    return out


def _ids(name: str, values: Optional[Iterable[Any]], kind: str) -> list[str]:
    out = [urn(v, kind) for v in (values or ())]
    if len(out) > MAX_FACET_VALUES:
        raise ValueError(f"`{name}` takes at most {MAX_FACET_VALUES} ids per call; got "
                         f"{len(out)}. Split the request.")
    return out


def _page_size(value: Optional[int], high: int) -> Optional[int]:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= high:
        raise ValueError(f"`page_size` must be an integer between 1 and {high}; got {value!r}.")
    return value


def _day(name: str, value: Any) -> Optional[_dt.date]:
    if value is None:
        return None
    if isinstance(value, _dt.date):
        return value
    if not isinstance(value, str) or not _DAY.match(value.strip()):
        raise ValueError(f"`{name}` must be a date YYYY-MM-DD; got {value!r}.")
    try:
        return _dt.date.fromisoformat(value.strip())
    except ValueError:
        raise ValueError(f"`{name}` is not a real date: {value!r}.") from None


def _search(criteria: list[tuple[str, list[str]]], test: Optional[bool]) -> Optional[str]:
    """`(status:(values:List(ACTIVE)),test:false)` — the `search` record of a finder."""
    parts = [f"{field}:(values:{restli_list(values)})" for field, values in criteria if values]
    if test is not None:
        parts.append(f"test:{'true' if test else 'false'}")
    return f"({','.join(parts)})" if parts else None


def _page(payload: Any) -> dict:
    if not isinstance(payload, dict):
        return {"elements": [], "next_page_token": None}
    meta = payload.get("metadata") or {}
    return {"elements": payload.get("elements") or [],
            "next_page_token": meta.get("nextPageToken") or None}


class LinkedInAdsClient:
    """Read-only on the ad accounts the person's token reaches. Every call is a GET."""

    def __init__(self, access_token: Optional[str] = None, *,
                 version: str = LINKEDIN_VERSION):
        self.access_token = require(access_token, "LINKEDIN_ADS_ACCESS_TOKEN")
        if not re.fullmatch(r"\d{6}", str(version or "")):
            raise ValueError(f"`version` must be YYYYMM; got {version!r}.")
        self.version = version
        self.session = requests.Session()
        # The token goes in a header, never in the URL.
        self.session.headers.update({
            "Authorization": f"Bearer {self.access_token}",
            "LinkedIn-Version": self.version,
            "X-Restli-Protocol-Version": "2.0.0",
            "Accept": "application/json",
        })

    def _get(self, path: str, pairs: Optional[list] = None, *,
             finder: bool = False) -> Any:
        query = _query(pairs or [])
        url = f"{API_BASE}{path}" + (f"?{query}" if query else "")
        headers = {"X-RestLi-Method": "FINDER"} if finder else None
        resp = self.session.get(url, headers=headers, timeout=HTTP_TIMEOUT,
                                allow_redirects=False)
        refuse_redirect(resp)
        raise_for_upstream(resp, service=SERVICE)
        try:
            return resp.json()
        except ValueError:
            return {}

    # --- accounts --------------------------------------------------------------------

    def list_account_roles(self) -> dict:
        """The ad accounts the person holds a role on, with that role
        (`ACCOUNT_BILLING_ADMIN`, `ACCOUNT_MANAGER`, `CAMPAIGN_MANAGER`,
        `CREATIVE_MANAGER`, `VIEWER`) and the person's URN (`user`)."""
        return self._get("/adAccountUsers", [("q", "authenticatedUser")])

    def search_ad_accounts(self, statuses: Optional[Iterable[str]] = None,
                           test: Optional[bool] = None, page_size: Optional[int] = None,
                           page_token: Optional[str] = None) -> dict:
        """Ad accounts the token reaches; all of them when no status is named."""
        search = _search([("status", _choices("statuses", statuses, ACCOUNT_STATUSES))],
                         test)
        return _page(self._get("/adAccounts", [
            ("q", "search"), ("search", search),
            ("pageSize", _page_size(page_size, MAX_PAGE_SIZE)),
            ("pageToken", _enc(page_token) if page_token else None)]))

    def get_ad_account(self, account_id: Any) -> dict:
        return self._get(f"/adAccounts/{entity_id(account_id, 'account')}")

    # --- campaign groups ---------------------------------------------------------------

    def search_campaign_groups(self, account_id: Any,
                               statuses: Optional[Iterable[str]] = None,
                               test: Optional[bool] = None,
                               page_size: Optional[int] = None,
                               page_token: Optional[str] = None) -> dict:
        """Campaign groups of one account (budget, schedule, serving statuses).
        Without `statuses`: every group but the deleted ones."""
        account = entity_id(account_id, "account")
        statuses = _choices("statuses", statuses, CAMPAIGN_GROUP_STATUSES) or list(
            DEFAULT_CAMPAIGN_GROUP_STATUSES)
        return _page(self._get(f"/adAccounts/{account}/adCampaignGroups", [
            ("q", "search"), ("search", _search([("status", statuses)], test)),
            ("pageSize", _page_size(page_size, MAX_PAGE_SIZE)),
            ("pageToken", _enc(page_token) if page_token else None)]))

    def get_campaign_group(self, account_id: Any, campaign_group_id: Any) -> dict:
        return self._get(f"/adAccounts/{entity_id(account_id, 'account')}/adCampaignGroups/"
                         f"{entity_id(campaign_group_id, 'campaign_group')}")

    # --- campaigns ---------------------------------------------------------------------

    def search_campaigns(self, account_id: Any, statuses: Optional[Iterable[str]] = None,
                         campaign_group_ids: Optional[Iterable[Any]] = None,
                         types: Optional[Iterable[str]] = None,
                         test: Optional[bool] = None, page_size: Optional[int] = None,
                         page_token: Optional[str] = None) -> dict:
        """Campaigns of one account, with their budgets (`dailyBudget`, `totalBudget`),
        bid (`unitCost`, `costType`, `optimizationTargetType`), objective, schedule and
        `targetingCriteria`. Without `statuses`: every campaign but the deleted ones."""
        account = entity_id(account_id, "account")
        statuses = _choices("statuses", statuses, CAMPAIGN_STATUSES) or list(
            DEFAULT_CAMPAIGN_STATUSES)
        search = _search([
            ("status", statuses),
            ("campaignGroup", _ids("campaign_group_ids", campaign_group_ids,
                                   "campaign_group")),
            ("type", _choices("types", types, CAMPAIGN_TYPES)),
        ], test)
        return _page(self._get(f"/adAccounts/{account}/adCampaigns", [
            ("q", "search"), ("search", search),
            ("pageSize", _page_size(page_size, MAX_PAGE_SIZE)),
            ("pageToken", _enc(page_token) if page_token else None)]))

    def get_campaign(self, account_id: Any, campaign_id: Any) -> dict:
        return self._get(f"/adAccounts/{entity_id(account_id, 'account')}/adCampaigns/"
                         f"{entity_id(campaign_id, 'campaign')}")

    # --- creatives ---------------------------------------------------------------------

    def search_creatives(self, account_id: Any,
                         campaign_ids: Optional[Iterable[Any]] = None,
                         intended_statuses: Optional[Iterable[str]] = None,
                         page_size: Optional[int] = None,
                         page_token: Optional[str] = None) -> dict:
        """Creatives of one account (`intendedStatus`, `isServing`,
        `servingHoldReasons`, `review.status`, the sponsored `content`)."""
        account = entity_id(account_id, "account")
        campaigns = _ids("campaign_ids", campaign_ids, "campaign")
        statuses = _choices("intended_statuses", intended_statuses, CREATIVE_STATUSES)
        return _page(self._get(f"/adAccounts/{account}/creatives", [
            ("q", "criteria"),
            ("campaigns", restli_list(campaigns) if campaigns else None),
            ("intendedStatuses", restli_list(statuses) if statuses else None),
            ("pageSize", _page_size(page_size, MAX_CREATIVE_PAGE_SIZE)),
            ("pageToken", _enc(page_token) if page_token else None)], finder=True))

    def get_creative(self, account_id: Any, creative_id: Any) -> dict:
        """One creative; its URN goes ENCODED in the path."""
        return self._get(f"/adAccounts/{entity_id(account_id, 'account')}/creatives/"
                         f"{_enc(urn(creative_id, 'creative'))}")

    # --- reporting ---------------------------------------------------------------------

    def get_analytics(self, pivots: Iterable[str], start: Any, end: Any = None, *,
                      time_granularity: str = "ALL",
                      account_ids: Optional[Iterable[Any]] = None,
                      campaign_group_ids: Optional[Iterable[Any]] = None,
                      campaign_ids: Optional[Iterable[Any]] = None,
                      creative_ids: Optional[Iterable[Any]] = None,
                      fields: Optional[Iterable[str]] = None) -> dict:
        """adAnalytics: one row per pivot value (and per period of `time_granularity`).

        One pivot → the analytics finder (professional demographics allowed); two or
        three → the statistics finder (no `MEMBER_*` pivot). At least one facet
        (accounts, campaign groups, campaigns, creatives). Dates inclusive, UTC; `end`
        open means up to today. `dateRange` and `pivotValues` are always returned.
        ⚠️ An empty `elements` means no activity OR no read access to that data."""
        pivots = _choices("pivots", pivots, PIVOTS)
        if not 1 <= len(pivots) <= MAX_PIVOTS:
            raise ValueError(f"`pivots` takes 1 to {MAX_PIVOTS} values; got {len(pivots)}.")
        if len(pivots) > 1 and set(pivots) & set(DEMOGRAPHIC_PIVOTS):
            raise ValueError("A MEMBER_* (professional demographic) pivot is only "
                             "accepted alone, one pivot per call.")
        granularity = _choices("time_granularity", [time_granularity],
                               TIME_GRANULARITIES)[0]
        day_start = _day("start", start)
        if day_start is None:
            raise ValueError("`start` is required (YYYY-MM-DD).")
        day_end = _day("end", end)
        if day_end is not None and day_end < day_start:
            raise ValueError("`end` is before `start`.")
        facets = [
            ("accounts", _ids("account_ids", account_ids, "account")),
            ("campaignGroups", _ids("campaign_group_ids", campaign_group_ids,
                                    "campaign_group")),
            ("campaigns", _ids("campaign_ids", campaign_ids, "campaign")),
            ("creatives", _ids("creative_ids", creative_ids, "creative")),
        ]
        if not any(values for _, values in facets):
            raise ValueError("Name at least one of account_ids, campaign_group_ids, "
                             "campaign_ids or creative_ids.")
        metrics = list(fields or DEFAULT_METRICS)
        for m in metrics:
            if not _METRIC.match(str(m)):
                raise ValueError(f"`fields` holds metric names (camelCase); got {m!r}.")
        metrics = [m for m in metrics if m not in ("dateRange", "pivotValues")]
        if len(metrics) > MAX_METRICS - 2:
            raise ValueError(f"`fields` takes at most {MAX_METRICS - 2} metrics (LinkedIn "
                             f"caps a call at {MAX_METRICS} fields, dateRange and "
                             f"pivotValues included); got {len(metrics)}.")
        date_range = f"(start:{restli_date(day_start)}" + (
            f",end:{restli_date(day_end)})" if day_end else ")")
        if len(pivots) == 1:
            head = [("q", "analytics"), ("pivot", pivots[0])]
        else:
            head = [("q", "statistics"), ("pivots", restli_list(pivots))]
        return self._get("/adAnalytics", head + [
            ("timeGranularity", granularity),
            ("dateRange", date_range),
            *[(name, restli_list(values)) for name, values in facets if values],
            ("fields", ",".join(["dateRange", "pivotValues", *metrics])),
        ])
