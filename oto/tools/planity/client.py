"""PlanityClient — single entry point orchestrating auth + the three API layers.

Caches:
- auth tokens (refreshed proactively)
- business metadata (after first lookup)
- Algolia credentials per business
- Open Firebase RTDB WebSockets (master + per-shard)
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Optional

import httpx

from .algolia import AlgoliaClient
from .auth import PlanityAuth
from .config import PlanityEndpoints
from .firebase_ws import FirebaseRTDB
from .rest_api import PlanityREST


@dataclass
class Employee:
    id: str
    name: str
    color: Optional[str] = None
    picture: Optional[str] = None
    calendar_id: Optional[str] = None


@dataclass
class SalonInfo:
    id: str
    name: str
    slug: str
    phone: Optional[str]
    db_shard: str
    calendars: list[str] = field(default_factory=list)
    opening_hours: Optional[str] = None
    employees: list[Employee] = field(default_factory=list)


class PlanityClient:
    def __init__(self, email: str, password: str, endpoints: PlanityEndpoints):
        # `endpoints` est OBLIGATOIRE et sans défaut : ce dépôt est public et ne
        # porte aucune coordonnée de Planity (cf. `config.PlanityEndpoints`).
        # Celui qui déploie le connecteur les pose, et répond de ce qu'il appelle.
        self._endpoints = endpoints
        self._http = httpx.AsyncClient(timeout=30.0)
        self.auth = PlanityAuth(email, password, endpoints, client=self._http)
        self.rest = PlanityREST(endpoints, client=self._http)
        self.algolia = AlgoliaClient(endpoints, client=self._http)

        self._salons: dict[str, SalonInfo] = {}
        self._master: Optional[FirebaseRTDB] = None
        self._shards: dict[str, FirebaseRTDB] = {}
        self._current_token: Optional[str] = None
        self._lock = asyncio.Lock()

    async def close(self):
        for db in list(self._shards.values()):
            await db.close()
        if self._master:
            await self._master.close()
        await self._http.aclose()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        await self.close()

    # ─── connection plumbing ───

    async def _ensure_master(self) -> FirebaseRTDB:
        async with self._lock:
            tokens = await self.auth.get_tokens()
            if self._master and self._current_token == tokens.id_token:
                return self._master
            if self._master:
                await self._master.close()
            for db in self._shards.values():
                await db.close()
            self._shards.clear()
            self._master = FirebaseRTDB.master(
                tokens.id_token, self._endpoints.firebase_app_id)
            await self._master.connect()
            self._current_token = tokens.id_token
            return self._master

    async def _ensure_shard(self, shard_name: str) -> FirebaseRTDB:
        async with self._lock:
            tokens = await self.auth.get_tokens()
            if shard_name in self._shards and self._current_token == tokens.id_token:
                return self._shards[shard_name]
            if shard_name in self._shards:
                await self._shards[shard_name].close()
            db = FirebaseRTDB.business_shard(
                shard_name, tokens.id_token, self._endpoints.firebase_app_id)
            await db.connect()
            self._shards[shard_name] = db
            return db

    # ─── Référentiel ───

    async def list_salons(self) -> list[SalonInfo]:
        tokens = await self.auth.get_tokens()
        master = await self._ensure_master()
        results: list[SalonInfo] = []
        for bid in tokens.business_ids:
            if bid in self._salons:
                results.append(self._salons[bid])
                continue
            name = await master.get(f"businesses/{bid}/name") or "?"
            slug = await master.get(f"businesses/{bid}/slug") or ""
            phone_raw = await master.get(f"businesses/{bid}/phoneNumber")
            phone = phone_raw if isinstance(phone_raw, str) else None
            db_shard = await master.get(f"businesses/{bid}/db") or "master"
            opening = await master.get(f"businesses/{bid}/openingHours")
            calendars = await master.get(f"businesses/{bid}/calendars")
            cal_ids: list[str] = []
            employees: list[Employee] = []
            if isinstance(calendars, dict):
                for cid, cdata in calendars.items():
                    cal_ids.append(cid)
                    children = (cdata or {}).get("children", {}) if isinstance(cdata, dict) else {}
                    if isinstance(children, dict):
                        for child_id, child in children.items():
                            if not isinstance(child, dict):
                                continue
                            employees.append(Employee(
                                id=child_id,
                                name=(child.get("name") or "").strip(),
                                color=child.get("color"),
                                picture=child.get("picture"),
                                calendar_id=cid,
                            ))
            info = SalonInfo(
                id=bid, name=name, slug=slug, phone=phone, db_shard=db_shard,
                calendars=cal_ids, opening_hours=opening if isinstance(opening, str) else None,
                employees=employees,
            )
            self._salons[bid] = info
            results.append(info)
        return results

    async def get_salon(self, salon_id: str) -> SalonInfo:
        if salon_id in self._salons:
            return self._salons[salon_id]
        await self.list_salons()
        if salon_id not in self._salons:
            raise ValueError(f"Salon {salon_id} not accessible")
        return self._salons[salon_id]

    async def list_services(self, salon_id: str) -> dict[str, dict]:
        """Service groups from master. Structure: {groupId: {children: {childId: svc}, ...}}."""
        await self.get_salon(salon_id)
        master = await self._ensure_master()
        data = await master.get(f"businesses/{salon_id}/services")
        return data if isinstance(data, dict) else {}

    async def list_products(self, salon_id: str) -> dict[str, dict]:
        """Product categories from business shard. Structure mirrors services
        ({categoryId: {children: {productId: product}}})."""
        salon = await self.get_salon(salon_id)
        shard = await self._ensure_shard(salon.db_shard)
        data = await shard.get(f"business_products/{salon_id}")
        return data if isinstance(data, dict) else {}

    # ─── Customers ───

    async def search_customers(self, salon_id: str, query: str = "", limit: int = 10) -> list[dict]:
        tokens = await self.auth.get_tokens()
        creds = await self.algolia.get_credentials(tokens.id_token, salon_id)
        resp = await self.algolia.search_customers(creds, query, hits_per_page=limit)
        return resp.get("hits", [])

    async def get_customer(self, salon_id: str, customer_id: str) -> dict:
        salon = await self.get_salon(salon_id)
        shard = await self._ensure_shard(salon.db_shard)
        data = await shard.get(f"business_customers/{salon_id}/{customer_id}")
        return data or {}

    async def get_customer_stats(self, salon_id: str, customer_id: str) -> dict:
        tokens = await self.auth.get_tokens()
        return await self.rest.get_customer_stats(salon_id, customer_id, tokens.id_token)

    async def get_customer_receipts(self, salon_id: str, customer_id: str) -> list[dict]:
        tokens = await self.auth.get_tokens()
        return await self.rest.get_customer_receipts(salon_id, customer_id, tokens.id_token)

    # ─── Planning / Appointments ───

    async def list_appointments(self, salon_id: str, calendar_id: Optional[str] = None) -> dict:
        salon = await self.get_salon(salon_id)
        cid = calendar_id or (salon.calendars[0] if salon.calendars else None)
        if not cid:
            return {}
        tokens = await self.auth.get_tokens()
        # Calendars DB is a different Firebase project — per-calendar shard
        db = FirebaseRTDB.calendars_shard(
            cid, tokens.id_token, self._endpoints.firebase_app_id)
        await db.connect()
        try:
            return await db.get(f"calendars/{cid}/vevents") or {}
        finally:
            await db.close()

    async def get_appointment(self, salon_id: str, vevent_id: str,
                               calendar_id: Optional[str] = None) -> dict:
        salon = await self.get_salon(salon_id)
        cid = calendar_id or (salon.calendars[0] if salon.calendars else None)
        if not cid:
            return {}
        tokens = await self.auth.get_tokens()
        db = FirebaseRTDB.calendars_shard(
            cid, tokens.id_token, self._endpoints.firebase_app_id)
        await db.connect()
        try:
            return await db.get(f"calendars/{cid}/vevents/{vevent_id}") or {}
        finally:
            await db.close()

    # ─── Business stats ───

    async def get_key_indicators(self, salon_id: str, gte_ms: int, lte_ms: int) -> dict:
        tokens = await self.auth.get_tokens()
        return await self.rest.get_key_indicators(salon_id, tokens.id_token, gte_ms, lte_ms)

    async def get_revenues(self, salon_id: str, gte_ms: int, lte_ms: int) -> dict:
        tokens = await self.auth.get_tokens()
        return await self.rest.get_revenues(salon_id, tokens.id_token, gte_ms, lte_ms)

    async def get_best_customers(self, salon_id: str, gte_ms: int, lte_ms: int) -> dict:
        tokens = await self.auth.get_tokens()
        return await self.rest.get_best_customers(salon_id, tokens.id_token, gte_ms, lte_ms)

    async def get_new_customers(self, salon_id: str, gte_ms: int, lte_ms: int) -> dict:
        tokens = await self.auth.get_tokens()
        return await self.rest.get_new_customers(salon_id, tokens.id_token, gte_ms, lte_ms)

    async def get_overall_frequencies(self, salon_id: str, gte_ms: int, lte_ms: int) -> dict:
        tokens = await self.auth.get_tokens()
        return await self.rest.get_overall_frequencies(salon_id, tokens.id_token, gte_ms, lte_ms)

    async def _seller_and_calendar_ids(self, salon_id: str) -> tuple[list[str], list[str]]:
        salon = await self.get_salon(salon_id)
        return [e.id for e in salon.employees], salon.calendars

    async def get_revenue_breakdown(self, salon_id: str, gte_ms: int, lte_ms: int) -> dict:
        seller_ids, cal_ids = await self._seller_and_calendar_ids(salon_id)
        tokens = await self.auth.get_tokens()
        return await self.rest.get_revenue_breakdown(salon_id, tokens.id_token, gte_ms, lte_ms,
            seller_ids=seller_ids, calendar_ids=cal_ids)

    async def get_calendar_stats(self, salon_id: str, gte_ms: int, lte_ms: int) -> dict:
        seller_ids, cal_ids = await self._seller_and_calendar_ids(salon_id)
        tokens = await self.auth.get_tokens()
        return await self.rest.get_calendar_stats(salon_id, tokens.id_token, gte_ms, lte_ms,
            seller_ids=seller_ids, calendar_ids=cal_ids)

    async def get_occupancy_rate(self, salon_id: str, gte_ms: int, lte_ms: int) -> dict:
        seller_ids, cal_ids = await self._seller_and_calendar_ids(salon_id)
        tokens = await self.auth.get_tokens()
        return await self.rest.get_occupancy_rate(salon_id, tokens.id_token, gte_ms, lte_ms,
            seller_ids=seller_ids, calendar_ids=cal_ids)

    async def get_reviews_stats(self, salon_id: str, gte_ms: int, lte_ms: int) -> dict:
        seller_ids, cal_ids = await self._seller_and_calendar_ids(salon_id)
        tokens = await self.auth.get_tokens()
        return await self.rest.get_reviews_stats(salon_id, tokens.id_token, gte_ms, lte_ms,
            seller_ids=seller_ids, calendar_ids=cal_ids)
