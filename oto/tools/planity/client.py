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

from . import appointments as _rdv
from . import pos as _pos
from . import stock as _stock
from .algolia import AlgoliaClient
from .auth import PlanityAuth
from .config import PlanityEndpoints
from .firebase_ws import FirebaseRTDB, calendar_shard_index
from .rest_api import PlanityREST


@dataclass
class Employee:
    """Un ENFANT d'agenda. Souvent une collaboratrice — pas toujours.

    `deleted_at` est renseigné quand l'enfant a été supprimé côté Planity : son
    agenda reste lisible (les rendez-vous passés y sont), mais il ne compte plus
    dans l'équipe. Le confondre avec un actif fait annoncer sept collaboratrices à
    un salon qui en a trois.

    `type` et `title` distinguent l'enfant qui n'est PAS une personne — une cabine,
    un poste, une ressource. Ils sont rendus tels quels : ce sont les valeurs de
    l'amont, et leur donner un sens ici en inventerait un."""

    id: str
    name: str
    color: Optional[str] = None
    picture: Optional[str] = None
    calendar_id: Optional[str] = None
    deleted_at: Optional[int] = None
    type: Optional[str] = None
    title: Optional[str] = None

    @property
    def deleted(self) -> bool:
        return self.deleted_at is not None


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

    async def _ensure_calendars_shard(self, child_id: str) -> FirebaseRTDB:
        """La base `calendars-N` de cet enfant d'agenda, gardée ouverte.

        Elle est indexée par un CALCUL sur l'identifiant, pas par une lecture — et
        elle ne sert que les salons SANS shard métier (`_agenda_db`)."""
        cle = f"calendars-{calendar_shard_index(child_id)}"
        async with self._lock:
            tokens = await self.auth.get_tokens()
            if cle in self._shards and self._current_token == tokens.id_token:
                return self._shards[cle]
            if cle in self._shards:
                await self._shards[cle].close()
            db = FirebaseRTDB.calendars_shard(
                child_id, tokens.id_token, self._endpoints.firebase_app_id)
            await db.connect()
            self._shards[cle] = db
            return db

    async def _agenda_db(self, salon: SalonInfo, child_id: str) -> FirebaseRTDB:
        """Où vivent les rendez-vous de ce salon.

        Sur le **shard métier** dès qu'il en a un ; la base `calendars-N` ne les
        sert qu'à défaut. Viser la mauvaise rend un nœud vide, jamais un refus :
        l'agenda se lit alors comme un agenda sans rendez-vous."""
        if salon.db_shard and salon.db_shard != "master":
            return await self._ensure_shard(salon.db_shard)
        return await self._ensure_calendars_shard(child_id)

    async def _enfants_dagenda(self, salon_id: str,
                               employee_id: Optional[str] = None) -> tuple[SalonInfo, list[str]]:
        """Le salon et les enfants d'agenda à lire — tous, ou celui qu'on demande.

        Les enfants SUPPRIMÉS sont lus comme les autres : leur agenda garde les
        rendez-vous passés, et les écarter ferait disparaître de l'historique une
        collaboratrice partie — un chiffre d'affaires en moins sans rien qui le
        signale."""
        salon = await self.get_salon(salon_id)
        ids = [e.id for e in salon.employees]
        if employee_id is None:
            return salon, ids
        if employee_id not in ids:
            # Lire un enfant qui n'est pas de ce salon rendrait un agenda vide, et
            # une faute de frappe se lirait comme « cette collaboratrice n'a rien ».
            raise ValueError(
                f"{employee_id} n'est pas un agenda de ce salon — "
                f"`list_employees` donne les identifiants qui en sont.")
        return salon, [employee_id]

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
                                deleted_at=child.get("deletedAt"),
                                type=child.get("type"),
                                title=child.get("title"),
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

    async def list_appointments(self, salon_id: str, day_from: str, day_to: str,
                                employee_id: Optional[str] = None) -> list[dict]:
        """Les rendez-vous du salon entre deux JOURS (`AAAA-MM-JJ`), bornes comprises.

        La fenêtre est en jours et pas en horodatage : l'index de tri de Planity
        porte `"AAAA-MM-JJ HH:MM"` en heure murale, sans décalage — le convertir en
        millisecondes ferait perdre ou gagner une heure aux deux bouts selon la
        saison, et un rendez-vous de plus ou de moins ne se remarque pas.

        Un rendez-vous ANNULÉ est rendu comme les autres, avec `cancelled=True` :
        il n'y a pas de champ « statut » chez Planity, seulement une date de
        suppression, et le filtrer d'office cacherait les annulations à qui les
        cherche."""
        salon, enfants = await self._enfants_dagenda(salon_id, employee_id)
        sortie: list[dict] = []
        for child_id in enfants:
            db = await self._agenda_db(salon, child_id)
            sortie += await _rdv.lire_jours(db, child_id, day_from, day_to)
        sortie.sort(key=lambda v: (v.get("start") or "", v.get("child_id") or ""))
        return sortie

    async def get_appointment(self, salon_id: str, vevent_id: str,
                              employee_id: Optional[str] = None) -> Optional[dict]:
        """Un rendez-vous par son identifiant.

        Sans `employee_id`, les agendas du salon sont parcourus jusqu'à le trouver :
        un identifiant de rendez-vous ne dit pas de quel agenda il vient, et
        l'appelant ne l'a pas toujours."""
        salon, enfants = await self._enfants_dagenda(salon_id, employee_id)
        for child_id in enfants:
            db = await self._agenda_db(salon, child_id)
            trouve = await _rdv.lire_un(db, child_id, vevent_id)
            if trouve is not None:
                return trouve
        return None

    async def list_recurring_appointments(self, salon_id: str,
                                          employee_id: Optional[str] = None,
                                          limit: int = 100) -> list[dict]:
        """Les rendez-vous récurrents — invisibles à toute lecture par jour."""
        salon, enfants = await self._enfants_dagenda(salon_id, employee_id)
        sortie: list[dict] = []
        for child_id in enfants:
            db = await self._agenda_db(salon, child_id)
            sortie += await _rdv.lire_recurrents(db, child_id, limit)
        return sortie

    # ─── Caisse ───

    async def list_pos_periods(self, salon_id: str, gte_ms: int, lte_ms: int,
                               limit: Optional[int] = None) -> list[dict]:
        """Les sessions de caisse de la fenêtre, sans leurs tickets."""
        salon = await self.get_salon(salon_id)
        db = await self._ensure_shard(salon.db_shard)
        return await _pos.lire_periodes(db, salon_id, gte_ms, lte_ms, limit)

    async def get_pos_period(self, salon_id: str, period_id: str) -> Optional[dict]:
        """Une session de caisse AVEC ses tickets."""
        salon = await self.get_salon(salon_id)
        db = await self._ensure_shard(salon.db_shard)
        return await _pos.lire_periode(db, salon_id, period_id)

    async def get_receipt(self, salon_id: str, period_id: str,
                          receipt_id: str) -> Optional[dict]:
        """Un ticket. Il vit sous sa période — il n'a pas d'adresse à lui."""
        salon = await self.get_salon(salon_id)
        db = await self._ensure_shard(salon.db_shard)
        return await _pos.lire_ticket(db, salon_id, period_id, receipt_id)

    async def list_payment_methods(self, salon_id: str) -> list[dict]:
        salon = await self.get_salon(salon_id)
        db = await self._ensure_shard(salon.db_shard)
        return await _pos.lire_moyens_paiement(db, salon_id)

    # ─── Stock ───

    async def list_stock_movements(self, salon_id: str, product_ids: list[str],
                                   gte_ms: int, lte_ms: int) -> list[dict]:
        """Les mouvements de stock de ces produits, une lecture bornée par produit."""
        salon = await self.get_salon(salon_id)
        db = await self._ensure_shard(salon.db_shard)
        return await _stock.lire_mouvements(db, salon_id, product_ids, gte_ms, lte_ms)

    async def list_mass_stock_removals(self, salon_id: str, limit: int = 50) -> list[dict]:
        salon = await self.get_salon(salon_id)
        db = await self._ensure_shard(salon.db_shard)
        return await _stock.lire_sorties_de_masse(db, salon_id, limit)

    async def list_suppliers(self, salon_id: str) -> list[dict]:
        tokens = await self.auth.get_tokens()
        return await self.rest.get_products_suppliers(salon_id, tokens.id_token)

    async def list_product_orders(self, salon_id: str,
                                  cursor: Optional[str] = None) -> dict:
        tokens = await self.auth.get_tokens()
        return await self.rest.get_products_orders(salon_id, tokens.id_token, cursor)

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

    async def get_revenue_by_payment_method(self, salon_id: str, gte_ms: int,
                                            lte_ms: int) -> dict:
        seller_ids, cal_ids = await self._seller_and_calendar_ids(salon_id)
        tokens = await self.auth.get_tokens()
        return await self.rest.get_revenue_by_payment_method(
            salon_id, tokens.id_token, gte_ms, lte_ms,
            seller_ids=seller_ids, calendar_ids=cal_ids)

    async def get_revenue_by_vat(self, salon_id: str, gte_ms: int, lte_ms: int) -> dict:
        seller_ids, cal_ids = await self._seller_and_calendar_ids(salon_id)
        tokens = await self.auth.get_tokens()
        return await self.rest.get_revenue_by_vat(
            salon_id, tokens.id_token, gte_ms, lte_ms,
            seller_ids=seller_ids, calendar_ids=cal_ids)

    async def get_service_stats(self, salon_id: str, gte_ms: int, lte_ms: int) -> dict:
        seller_ids, cal_ids = await self._seller_and_calendar_ids(salon_id)
        tokens = await self.auth.get_tokens()
        return await self.rest.get_service_stats(
            salon_id, tokens.id_token, gte_ms, lte_ms,
            seller_ids=seller_ids, calendar_ids=cal_ids)
