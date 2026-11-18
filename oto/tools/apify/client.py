"""Apify client — running hosted scraping "actors" (apify.com).

API v2, Bearer auth. Apify is not ONE scraper but a **catalog of scrapers**
(the *actors*, ~5000 in the Store: Google Maps, LinkedIn, Instagram, Amazon,
Booking…) that you launch with an input JSON and whose output you read from a
*dataset*. Hence the business path:

1. `store_search("google maps")` → spot the actor and its identifier.
2. `actor(actor_id)` → read its default options before launching it.
3. `run_sync_dataset_items(actor_id, input)` → launch AND fetch the results
   (up to 300 s), or `run()` + `run_status()` + `dataset_items()` for a long job.

An actor is billed by usage: `max_items` / `timeout_secs` / `max_total_charge_usd`
are the guardrails to set at launch, not afterwards.

Retries — Apify answers `429 rate-limit-exceeded` past its per-resource rate (60 req/s by
default) and asks for an exponential backoff from 500 ms, the wait drawn between the delay
and twice it (docs.apify.com/api/v2, « Rate limiting »). Each call site says what it may
retry (`_request(retry_on=…)`), nothing by default:

- the READS (store, actors, actor, run status, dataset items) and the abort (aborting twice
  stops the same run) retry a 429 and a gateway's 502 / 503 / 504;
- the STARTS (`run`, `run_sync_dataset_items`) retry a 429 ONLY. A 429 is the rate limiter
  refusing the request before anything runs: no run exists, replaying it starts one run. A
  5xx, a timeout or a dropped connection on a start is ambiguous — the run may have
  started — and Apify documents no idempotency key for a start: replaying it could start,
  and bill, a second run. It is raised, never replayed.

At most `MAX_RETRIES` retries; a `Retry-After` the answer carries is followed when it is
short (≤ `RETRY_AFTER_MAX_S`), and a longer one is not slept away: the error is raised at
once, its `retry_after` set, for the caller to decide.

Requires: requests
"""
from __future__ import annotations

import random
import time
from typing import Any, Dict, FrozenSet, List, Optional

import requests

from ..common.credentials import require
from ..common import raise_for_upstream
from ..common.errors import retry_after_seconds

#: Retries after the first send — four sends at most.
MAX_RETRIES = 3
#: First backoff delay, doubled at each retry (Apify's documented start), and its cap.
BACKOFF_S = 0.5
BACKOFF_MAX_S = 8.0
#: The longest `Retry-After` slept here; beyond, the error goes back to the caller.
RETRY_AFTER_MAX_S = 10.0

#: What a READ (or the abort) retries: the rate limit and a gateway's transient errors.
RETRY_READ: FrozenSet[int] = frozenset({429, 502, 503, 504})
#: What a START retries: the rate limit only — refused before processing, no run exists.
RETRY_START: FrozenSet[int] = frozenset({429})


def _sleep(seconds: float) -> None:
    """The wait between two sends — a seam, so a test does not sleep."""
    time.sleep(seconds)


def _backoff(attempt: int) -> float:
    """The wait before retry `attempt` (0-based): between the delay and twice it, the
    delay doubling from `BACKOFF_S`, capped at `BACKOFF_MAX_S`."""
    delay = min(BACKOFF_S * (2 ** attempt), BACKOFF_MAX_S)
    return random.uniform(delay, min(2 * delay, BACKOFF_MAX_S))


class ApifyClient:
    """Apify v2 client (https://api.apify.com/v2), Bearer auth `apify_api_…`."""

    BASE_URL = "https://api.apify.com/v2"

    def __init__(self, api_key: str = None):
        """
        Args:
            api_key: Apify token.
        """
        self.api_key = require(api_key, "APIFY_API_KEY")
        self.session = requests.Session()
        self.session.headers.update({"Authorization": f"Bearer {self.api_key}"})

    # --- transport ----------------------------------------------------------

    @staticmethod
    def _actor_path_id(actor_id: str) -> str:
        """Normalize `username/actor-name` → `username~actor-name` (URL form).

        The Store shows the actor as `apify/website-content-crawler`, the API expects it
        as `apify~website-content-crawler` — an unconverted slash would give a 404
        on a route that does not exist.
        """
        return actor_id.replace("/", "~")

    def _request(self, method: str, path: str, *, timeout: int = 60,
                 retry_on: FrozenSet[int] = frozenset(), **kwargs) -> Any:
        """One call, retried on the statuses `retry_on` names (none by default: a call
        site says what it may replay — module docstring, « Retries »)."""
        for attempt in range(MAX_RETRIES + 1):
            resp = self.session.request(method, f"{self.BASE_URL}{path}",
                                        timeout=timeout, **kwargs)
            if resp.status_code not in retry_on or attempt == MAX_RETRIES:
                break
            asked = retry_after_seconds(resp)
            if asked is not None and asked > RETRY_AFTER_MAX_S:
                break   # too long to hold here: raised with its `retry_after`
            _sleep(asked if asked is not None else _backoff(attempt))
        raise_for_upstream(resp, service="apify")
        return resp.json() if resp.content else {}

    @staticmethod
    def _compact(params: Dict[str, Any]) -> Dict[str, Any]:
        return {k: v for k, v in params.items() if v is not None}

    # --- catalog ------------------------------------------------------------

    def store_search(
        self,
        search: Optional[str] = None,
        limit: int = 20,
        offset: Optional[int] = None,
        category: Optional[str] = None,
        sort_by: Optional[str] = None,
    ) -> Dict[str, Any]:
        """GET /store — search for a public actor in the Apify Store.

        Args:
            search: free terms (e.g. "google maps reviews", "linkedin profile").
            category: Store category (e.g. "ECOMMERCE", "SOCIAL_MEDIA").
            sort_by: `"relevance"` | `"popularity"` | `"newest"` | `"lastUpdate"`.

        Returns: `{data: {items: [{id, name, username, title, description, stats,
            pricingInfos, …}], total, …}}`. The identifier to run is
            `username/name` (or `id`).
        """
        params = self._compact({
            "search": search, "limit": limit, "offset": offset,
            "category": category, "sortBy": sort_by,
        })
        return self._request("GET", "/store", params=params, retry_on=RETRY_READ)

    def actors(self, limit: int = 50, offset: Optional[int] = None,
               desc: Optional[bool] = None) -> Dict[str, Any]:
        """GET /actors — the account's actors (its own, not the public Store)."""
        params = self._compact({"limit": limit, "offset": offset,
                                "desc": 1 if desc else None})
        return self._request("GET", "/actors", params=params, retry_on=RETRY_READ)

    def actor(self, actor_id: str) -> Dict[str, Any]:
        """GET /actors/{id} — an actor's card: builds, `defaultRunOptions`
        (default memory and timeout), versions. Read it before a first
        launch to size `memory_mbytes`/`timeout_secs`."""
        return self._request("GET", f"/actors/{self._actor_path_id(actor_id)}",
                             retry_on=RETRY_READ)

    # --- execution ----------------------------------------------------------

    def run_sync_dataset_items(
        self,
        actor_id: str,
        run_input: Optional[Dict[str, Any]] = None,
        max_items: Optional[int] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
        fields: Optional[List[str]] = None,
        timeout_secs: Optional[int] = None,
        memory_mbytes: Optional[int] = None,
        max_total_charge_usd: Optional[float] = None,
        build: Optional[str] = None,
        timeout: int = 310,
    ) -> Any:
        """POST /actors/{id}/run-sync-get-dataset-items — launches AND returns the results.

        The nominal path: a single call, the dataset items coming back. The API
        **cuts off at 300 s** (408 beyond) — for a long scrape, go through `run()`
        then `run_status()`/`dataset_items()`.

        Args:
            run_input: the actor's input JSON (its fields are specific to each
                actor — see its Store page).
            max_items: cap on BILLED items (pay-per-result actors).
            limit / offset / fields: pagination and projection of the output.
            timeout_secs / memory_mbytes: run budget on Apify's side.
            max_total_charge_usd: cost ceiling for the run.

        Returns: the LIST of dataset items (not a `{data: …}` envelope).
        """
        params = self._compact({
            "maxItems": max_items, "limit": limit, "offset": offset,
            "fields": ",".join(fields) if fields else None,
            "timeout": timeout_secs, "memory": memory_mbytes,
            "maxTotalChargeUsd": max_total_charge_usd, "build": build,
        })
        return self._request(
            "POST", f"/actors/{self._actor_path_id(actor_id)}/run-sync-get-dataset-items",
            params=params, json=run_input or {}, timeout=timeout, retry_on=RETRY_START,
        )

    def run(
        self,
        actor_id: str,
        run_input: Optional[Dict[str, Any]] = None,
        max_items: Optional[int] = None,
        timeout_secs: Optional[int] = None,
        memory_mbytes: Optional[int] = None,
        max_total_charge_usd: Optional[float] = None,
        build: Optional[str] = None,
        wait_for_finish: Optional[int] = None,
        timeout: int = 90,
    ) -> Dict[str, Any]:
        """POST /actors/{id}/runs — launch an actor WITHOUT waiting for it to finish.

        Args:
            wait_for_finish: max seconds to wait before handing control back (≤60) —
                handy to catch a very short run without re-polling.

        Returns: `{data: {id, actId, status, defaultDatasetId, startedAt, …}}` —
            `id` for `run_status`, `defaultDatasetId` for `dataset_items`.
        """
        params = self._compact({
            "maxItems": max_items, "timeout": timeout_secs, "memory": memory_mbytes,
            "maxTotalChargeUsd": max_total_charge_usd, "build": build,
            "waitForFinish": wait_for_finish,
        })
        return self._request(
            "POST", f"/actors/{self._actor_path_id(actor_id)}/runs",
            params=params, json=run_input or {}, timeout=timeout, retry_on=RETRY_START,
        )

    def run_status(self, run_id: str, wait_for_finish: Optional[int] = None,
                   timeout: int = 90) -> Dict[str, Any]:
        """GET /actor-runs/{id} — a run's state.

        `status` ∈ READY, RUNNING, SUCCEEDED, FAILED, TIMED-OUT, ABORTED. The
        response carries `defaultDatasetId` (where to read the output) and `usageTotalUsd`
        (what the run cost).
        """
        params = self._compact({"waitForFinish": wait_for_finish})
        return self._request("GET", f"/actor-runs/{run_id}", params=params, timeout=timeout,
                             retry_on=RETRY_READ)

    def abort_run(self, run_id: str, gracefully: Optional[bool] = None) -> Dict[str, Any]:
        """POST /actor-runs/{id}/abort — stop a run (stops billing)."""
        params = self._compact({"gracefully": "true" if gracefully else None})
        return self._request("POST", f"/actor-runs/{run_id}/abort", params=params,
                             retry_on=RETRY_READ)

    # --- output -------------------------------------------------------------

    def dataset_items(
        self,
        dataset_id: str,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
        fields: Optional[List[str]] = None,
        omit: Optional[List[str]] = None,
        desc: Optional[bool] = None,
        clean: Optional[bool] = None,
        timeout: int = 120,
    ) -> Any:
        """GET /datasets/{id}/items — the results produced by a run.

        Args:
            dataset_id: the run's `defaultDatasetId`.
            fields / omit: projection (useful — some actors return very wide
                objects).
            clean: drop empty / hidden items.

        Returns: the LIST of items (JSON format).
        """
        params = self._compact({
            "limit": limit, "offset": offset,
            "fields": ",".join(fields) if fields else None,
            "omit": ",".join(omit) if omit else None,
            "desc": 1 if desc else None,
            "clean": "true" if clean else None,
        })
        return self._request("GET", f"/datasets/{dataset_id}/items",
                             params=params, timeout=timeout, retry_on=RETRY_READ)
