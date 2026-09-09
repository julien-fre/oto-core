"""Thin wrapper around Planity's REST lambdas at product.api.euwest1.prod.planityapp.com.

Two payload conventions observed:
- customer-level: {businessId, customerId, token[, hasPOS]}
- business-level: {businessId, userToken, gte, lte}

Endpoints marked VERIFIED were tested end-to-end with real payloads. Others
(marked BEST_EFFORT) are implemented based on bundle introspection and may
return error until we capture the real payload from browser traffic.
"""
from __future__ import annotations

from typing import Optional

import httpx

from .config import HTTP_TIMEOUT, PLANITY_REST_API


class PlanityREST:
    def __init__(self, client: Optional[httpx.AsyncClient] = None):
        self._client = client or httpx.AsyncClient(timeout=30.0)
        self._owns = client is None

    async def close(self):
        if self._owns:
            await self._client.aclose()

    async def _call(self, endpoint: str, payload: dict) -> dict | list:
        r = await self._client.post(
            f"{PLANITY_REST_API}/{endpoint}",
            json=payload,
            headers={"Origin": "https://pro.planity.com"},
            timeout=HTTP_TIMEOUT,
        )
        r.raise_for_status()
        data = r.json()
        if isinstance(data, dict) and data.get("errorType"):
            raise RuntimeError(f"{endpoint}: {data.get('errorMessage')}")
        return data

    # ──────────────── Business-level (VERIFIED) ────────────────

    async def get_key_indicators(self, business_id: str, id_token: str, gte_ms: int, lte_ms: int) -> dict:
        """CA TTC/HT, nb tickets, TVA, panier moyen."""
        return await self._call("getBusinessKeyIndicators",
            {"businessId": business_id, "userToken": id_token, "gte": gte_ms, "lte": lte_ms})

    async def get_revenues(self, business_id: str, id_token: str, gte_ms: int, lte_ms: int) -> dict:
        """Daily revenue buckets: {'all': {ts_ms: {revenueWithVAT, revenueWithoutVAT, quantity}}}."""
        return await self._call("getBusinessRevenues",
            {"businessId": business_id, "userToken": id_token, "gte": gte_ms, "lte": lte_ms})

    async def get_best_customers(self, business_id: str, id_token: str, gte_ms: int, lte_ms: int,
                                  filter_: str = "list", has_pos: bool = True) -> dict:
        return await self._call("getBestCustomers",
            {"token": id_token, "businessId": business_id, "filter": filter_,
             "hasPOS": has_pos, "start": gte_ms, "end": lte_ms})

    async def get_new_customers(self, business_id: str, id_token: str, gte_ms: int, lte_ms: int,
                                 filter_: str = "list") -> dict:
        return await self._call("getNewCustomers",
            {"token": id_token, "businessId": business_id, "filter": filter_,
             "start": gte_ms, "end": lte_ms})

    async def get_overall_frequencies(self, business_id: str, id_token: str, gte_ms: int, lte_ms: int) -> dict:
        return await self._call("getOverallFrequencies",
            {"token": id_token, "businessId": business_id, "start": gte_ms, "end": lte_ms})

    # ──────────────── Customer-level (VERIFIED) ────────────────

    async def get_customer_stats(self, business_id: str, customer_id: str, id_token: str,
                                  has_pos: bool = True) -> dict:
        return await self._call("getCustomerStats",
            {"businessId": business_id, "customerId": customer_id, "token": id_token, "hasPOS": has_pos})

    async def get_customer_receipts(self, business_id: str, customer_id: str, id_token: str) -> list[dict]:
        result = await self._call("getCustomerReceipts",
            {"businessId": business_id, "customerId": customer_id, "token": id_token})
        return result if isinstance(result, list) else []

    # ──────────────── Statistiques business (VERIFIED) ────────────────

    async def get_revenue_breakdown(self, business_id: str, id_token: str, gte_ms: int, lte_ms: int,
                                    seller_ids: list[str], calendar_ids: list[str]) -> dict:
        """Multi-dimensional revenue breakdown in one call.

        Returns totals + bySeller + byProduct + byService + byOther + byGiftVoucherAtSale.
        """
        return await self._call("getBusinessRevenuesBySeller",
            {"businessId": business_id, "userToken": id_token, "gte": gte_ms, "lte": lte_ms,
             "sellers": seller_ids, "calendars": calendar_ids})

    def _stats_payload(self, business_id, id_token, gte_ms, lte_ms, seller_ids, calendar_ids):
        """Stats endpoints need BOTH userToken+token and BOTH gte/lte+start/end."""
        return {
            "businessId": business_id,
            "userToken": id_token, "token": id_token,
            "gte": gte_ms, "lte": lte_ms,
            "start": gte_ms, "end": lte_ms,
            "sellers": seller_ids, "calendars": calendar_ids,
        }

    async def get_calendar_stats(self, business_id: str, id_token: str, gte_ms: int, lte_ms: int,
                                  seller_ids: list[str], calendar_ids: list[str]) -> dict:
        """Per-seller calendar/revenue stats: bySeller.data[sellerId] = {onlineAppointments, ...}."""
        return await self._call("getCalendarStats",
            self._stats_payload(business_id, id_token, gte_ms, lte_ms, seller_ids, calendar_ids))

    async def get_occupancy_rate(self, business_id: str, id_token: str, gte_ms: int, lte_ms: int,
                                  seller_ids: list[str], calendar_ids: list[str]) -> dict:
        """Weekly occupancy heatmap (days × time slots, values 0..1+)."""
        return await self._call("getOccupancyRateStats",
            self._stats_payload(business_id, id_token, gte_ms, lte_ms, seller_ids, calendar_ids))

    async def get_reviews_stats(self, business_id: str, id_token: str, gte_ms: int, lte_ms: int,
                                 seller_ids: list[str], calendar_ids: list[str]) -> dict:
        """Review ratings aggregated by calendar and by service."""
        return await self._call("getReviewsStats",
            self._stats_payload(business_id, id_token, gte_ms, lte_ms, seller_ids, calendar_ids))
