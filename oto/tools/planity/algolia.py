"""Algolia search for customers.

Planity's /getCustomerSearchCredentials returns per-business API keys where
the businessId filter is pre-applied. So queries are automatically scoped.

Index name: business_customers (single global index, filter embedded in key).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import httpx

from .config import PLANITY_REST_API, SEARCH_TIMEOUT


@dataclass
class AlgoliaCredentials:
    app_id: str
    api_key: str

    @property
    def host(self) -> str:
        return f"{self.app_id.lower()}-dsn.algolia.net"


class AlgoliaClient:
    def __init__(self, client: Optional[httpx.AsyncClient] = None):
        self._client = client or httpx.AsyncClient(timeout=15.0)
        self._owns_client = client is None
        # Cache creds per (id_token, business_id)
        self._cred_cache: dict[tuple[str, str], AlgoliaCredentials] = {}

    async def close(self):
        if self._owns_client:
            await self._client.aclose()

    async def get_credentials(
        self, id_token: str, business_id: str, country_code: str = "FR"
    ) -> AlgoliaCredentials:
        cache_key = (id_token[:40], business_id)  # short prefix as cache key
        if cache_key in self._cred_cache:
            return self._cred_cache[cache_key]

        r = await self._client.post(
            f"{PLANITY_REST_API}/getCustomerSearchCredentials",
            json={
                "token": id_token,
                "businessId": business_id,
                "businessCountryCode": country_code,
                "withMainAppCredentials": True,
            },
            headers={"Origin": "https://pro.planity.com"},
            timeout=SEARCH_TIMEOUT,
        )
        r.raise_for_status()
        body = r.json()["body"]
        creds = AlgoliaCredentials(app_id=body["appId"], api_key=body["apiKey"])
        self._cred_cache[cache_key] = creds
        return creds

    async def search_customers(
        self,
        creds: AlgoliaCredentials,
        query: str = "",
        hits_per_page: int = 10,
        page: int = 0,
    ) -> dict:
        """Search the business_customers index. Returns the raw Algolia response."""
        r = await self._client.post(
            f"https://{creds.host}/1/indexes/business_customers/query",
            json={"query": query, "hitsPerPage": hits_per_page, "page": page},
            headers={
                "X-Algolia-Application-Id": creds.app_id,
                "X-Algolia-API-Key": creds.api_key,
            },
            timeout=SEARCH_TIMEOUT,
        )
        r.raise_for_status()
        return r.json()
