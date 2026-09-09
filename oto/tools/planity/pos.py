"""La caisse : périodes, tickets, lignes, paiements.

Une **période** est une session de caisse (ouverture → clôture) ; elle porte ses
tickets en ligne, sous `receipts`. Il y en a des centaines sur un salon : toute
lecture passe par une plage sur `createdAt`, jamais par le nœud entier.

⚠️ **Un ticket porte un instantané COMPLET de la cliente** — nom, téléphone,
email, adresse, commentaire — figé au moment de l'encaissement. Ce module est une
bibliothèque et rend ce que Planity donne. La projection se décide à la frontière
d'un outil, et elle s'y réduit à l'identifiant : ni nom, ni contact, ni adresse.
Le connecteur backend porte cette règle et sa raison."""
from __future__ import annotations

from typing import Optional

from .firebase_ws import FirebaseRTDB, range_on

NOEUD_PERIODES = "pos_periods"
NOEUD_MOYENS_PAIEMENT = "business_payment_methods"

#: L'index de tri des périodes de caisse. Millisecondes, comme partout chez Planity.
INDEX_PERIODE = "createdAt"


def _ligne(brut: dict) -> dict:
    """Une ligne de ticket. `title` nomme la PRESTATION ou le PRODUIT, pas la cliente."""
    return {
        "title": brut.get("title"),
        "price_cents": brut.get("price"),
        "unit_price_cents": brut.get("unitPrice"),
        "quantity": brut.get("quantity"),
        "service_id": brut.get("serviceId"),
        "product_id": brut.get("productId"),
        "seller_id": brut.get("seller"),
        "duration_minutes": brut.get("duration"),
        "vat_code": brut.get("vatCode"),
        "vat_rate": brut.get("vatRate"),
        "vat_excluded_cents": brut.get("vatExcluded"),
        "from_appointment": brut.get("comingFromAppointment"),
    }


def _paiement(brut: dict) -> dict:
    return {
        "method": brut.get("method"),
        "amount_cents": brut.get("amount"),
        "tip_cents": brut.get("tpeTip"),
    }


def ticket(receipt_id: str, brut: dict) -> dict:
    """Un ticket nommé. `customer` reste tel quel — cf. l'avertissement du module."""
    lignes = brut.get("lines") or {}
    paiements = brut.get("paymentMethods") or {}
    rdv = brut.get("appointment") or {}
    client = brut.get("customer")
    return {
        "id": receipt_id,
        "number": brut.get("number"),
        "sequence": brut.get("sequence"),
        "created_at": brut.get("createdAt"),
        "operation_type": brut.get("operationType"),
        "lines_count": brut.get("linesCount"),
        "lines": [_ligne(l) for l in _valeurs(lignes) if isinstance(l, dict)],
        "payments": [_paiement(p) for p in _valeurs(paiements) if isinstance(p, dict)],
        "discount_total_cents": brut.get("discountTotal"),
        "vat_included_total_cents": brut.get("vatIncludedTotal"),
        "vat_excluded_total_cents": brut.get("vatExcludedTotal"),
        "vat_total_cents": brut.get("vatTotal"),
        "vat_rates": brut.get("vatRates"),
        "seller_id": brut.get("userId"),
        "seller_name": brut.get("userName"),
        # Un ticket annulé porte `status`; un ticket normal n'a pas le champ du
        # tout. Le rendre à `None` ferait lire « pas de statut » comme « annulé
        # inconnu » — il vaut `"OK"` par ABSENCE, ce que dit `cancelled`.
        "status": brut.get("status"),
        "cancelled": brut.get("status") == "CANCELLED",
        "cancelled_at": brut.get("cancelledAt"),
        "cancelled_by": brut.get("cancelledBy"),
        # `appointment` est une MAP {veventId: {...}} : c'est la clé qui porte le
        # lien vers l'agenda, pas une valeur à l'intérieur.
        "appointment_ids": sorted(rdv.keys()) if isinstance(rdv, dict) else [],
        "customer_id": client.get("id") if isinstance(client, dict) else None,
        "customer": client,
        "raw": brut,
    }


def _valeurs(noeud) -> list:
    """Planity écrit ses collections tantôt en map, tantôt en liste."""
    if isinstance(noeud, dict):
        return list(noeud.values())
    if isinstance(noeud, list):
        return noeud
    return []


def periode(period_id: str, brut: dict, avec_tickets: bool = True) -> dict:
    tickets = brut.get("receipts") or {}
    sortie = {
        "id": period_id,
        "created_at": brut.get("createdAt"),
        "closed_at": brut.get("closedAt"),
        "open": brut.get("closedAt") is None,
        "initial_amount_cents": brut.get("initialAmount"),
        "final_amount_cents": brut.get("finalAmount"),
        "sequences": brut.get("sequences"),
        "receipts_count": len(tickets) if isinstance(tickets, dict) else 0,
    }
    if avec_tickets and isinstance(tickets, dict):
        sortie["receipts"] = [ticket(rid, r) for rid, r in tickets.items()
                              if isinstance(r, dict)]
    return sortie


async def lire_periodes(db: FirebaseRTDB, business_id: str, gte_ms: int, lte_ms: int,
                        limite: Optional[int] = None) -> list[dict]:
    """Les périodes de caisse ouvertes dans la fenêtre, SANS leurs tickets.

    Sans tickets délibérément : une période en porte des dizaines, chacun avec un
    instantané de cliente. Une liste de périodes qui les embarquerait ferait
    transiter des milliers de fiches pour répondre « combien de sessions ce
    mois-ci »."""
    brut = await db.get(f"{NOEUD_PERIODES}/{business_id}",
                        range_on(INDEX_PERIODE, gte_ms, lte_ms, limit=limite))
    if not isinstance(brut, dict):
        return []
    periodes = [periode(pid, p, avec_tickets=False)
                for pid, p in brut.items() if isinstance(p, dict)]
    periodes.sort(key=lambda p: p.get("created_at") or 0)
    return periodes


async def lire_periode(db: FirebaseRTDB, business_id: str, period_id: str) -> Optional[dict]:
    brut = await db.get(f"{NOEUD_PERIODES}/{business_id}/{period_id}")
    if not isinstance(brut, dict) or not brut:
        return None
    return periode(period_id, brut, avec_tickets=True)


async def lire_ticket(db: FirebaseRTDB, business_id: str, period_id: str,
                      receipt_id: str) -> Optional[dict]:
    """Un ticket précis. Il vit SOUS sa période — il n'a pas d'adresse à lui."""
    brut = await db.get(
        f"{NOEUD_PERIODES}/{business_id}/{period_id}/receipts/{receipt_id}")
    # Vide = absent. Un ticket squelette se lirait comme un ticket à zéro euro.
    if not isinstance(brut, dict) or not brut:
        return None
    return ticket(receipt_id, brut)


async def lire_moyens_paiement(db: FirebaseRTDB, business_id: str) -> list[dict]:
    """Les moyens de paiement du salon — la table qui donne son nom à `method`."""
    brut = await db.get(f"{NOEUD_MOYENS_PAIEMENT}/{business_id}")
    if not isinstance(brut, dict):
        return []
    return [{"id": mid, "name": m.get("name"), "color": m.get("color"),
             "sort": m.get("sort")}
            for mid, m in brut.items() if isinstance(m, dict)]
