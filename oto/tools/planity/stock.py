"""Le stock : lots d'achat, mouvements, sorties de masse.

Le stock d'un produit n'est pas un nombre — c'est une MAP de lots d'achat
(`stocks`), chacun avec sa quantité restante et son prix d'achat. Sommer les
quantités donne le stock ; ignorer les lots fait disparaître le prix d'achat, donc
la marge.

Les mouvements vivent sous `business_stock_movements/<salon>/<produit>` : un
mouvement PAR PRODUIT, des milliers en tout. Il n'y a pas de lecture globale qui
tienne — on lit produit par produit, sur une plage de `createdAt`.

⚠️ **La liste des produits se prend au CATALOGUE, pas au nœud des mouvements.**
Ce dernier se lit borné, et une borne y tronque en silence : sur un salon à neuf
cents produits, les derniers n'ont simplement pas de mouvement — ce qui se lit
comme « rien vendu » et fausse toute prévision de commande.
"""
from __future__ import annotations

from typing import Iterable

from .firebase_ws import FirebaseRTDB, limit_last, range_on

NOEUD_MOUVEMENTS = "business_stock_movements"
NOEUD_SORTIES_DE_MASSE = "business_mass_removed_stocks"
NOEUD_PRODUITS = "business_products"

INDEX_MOUVEMENT = "createdAt"

#: Les types de mouvement du modèle. `sale` porte la consommation,
#: `saleCancellation` la reprend. Un type hors de cette liste n'est PAS filtré :
#: elle documente, elle ne décide pas.
TYPES_CONNUS = ("creation", "sale", "update", "saleCancellation")


def produit(product_id: str, category_id: str, brut: dict) -> dict:
    """Un produit du catalogue, ses lots et ses seuils.

    `stock_threshold` / `stock_ceiling` / `supplier_id` existent dans le modèle de
    Planity et peuvent n'être renseignés nulle part : `None` veut dire « le salon
    ne s'en sert pas », pas « zéro ». Une prévision de commande qui lirait `0` en
    seuil commanderait tout, tout le temps."""
    lots_bruts = brut.get("stocks") or {}
    lots = []
    quantite = 0
    if isinstance(lots_bruts, dict):
        for lot_id, lot in lots_bruts.items():
            if not isinstance(lot, dict):
                continue
            q = int(lot.get("quantity") or 0)
            quantite += q
            lots.append({
                "id": lot_id,
                "quantity": q,
                "purchase_price_cents": lot.get("purchasePrice"),
                "initial_purchase_price_cents": lot.get("initialPurchasePrice"),
                "created_at": lot.get("createdAt"),
                "updated_at": lot.get("updatedAt"),
            })
    lots.sort(key=lambda l: l.get("created_at") or 0)
    return {
        "id": product_id,
        "category_id": category_id,
        "name": (brut.get("name") or "").strip(),
        "price_cents": brut.get("price"),
        "ean": brut.get("eanCode"),
        "brand": brut.get("brand"),
        "stock_total": quantite,
        "stock_lots": lots,
        "stock_threshold": brut.get("stockThreshold"),
        "stock_ceiling": brut.get("stockCeiling"),
        "supplier_id": brut.get("supplierId"),
        "click_and_collect": brut.get("clickAndCollect"),
        "deleted_at": brut.get("deletedAt"),
        "deleted": brut.get("deletedAt") is not None,
    }


def aplatir_produits(catalogue: dict) -> list[dict]:
    """Le catalogue `{catégorie: {children: {produit}}}` à plat."""
    sortie = []
    for cat_id, cat in (catalogue or {}).items():
        if not isinstance(cat, dict):
            continue
        enfants = cat.get("children") or {}
        if not isinstance(enfants, dict):
            continue
        for pid, p in enfants.items():
            if isinstance(p, dict):
                sortie.append(produit(pid, cat_id, p))
    return sortie


def mouvement(product_id: str, mov_id: str, brut: dict) -> dict:
    """Un mouvement nommé.

    ⚠️ **`purchasePrice` n'est pas toujours un nombre** : il vaut aussi la chaîne
    `"any"` (une sortie qui ne vise aucun lot d'achat en particulier). Le convertir
    en euros sans regarder lève au premier mouvement de ce genre — au milieu d'une
    lecture par ailleurs bonne. On sépare donc les deux : `purchase_price_cents`
    est le montant QUAND c'en est un, `purchase_price_raw` est ce que l'amont a
    écrit. Un `None` en centimes veut dire « pas un montant », pas « gratuit »."""
    achat = brut.get("purchasePrice")
    montant = achat if isinstance(achat, (int, float)) and not isinstance(achat, bool) else None
    return {
        "id": mov_id,
        "product_id": product_id,
        "created_at": brut.get("createdAt"),
        "quantity": brut.get("quantity"),
        "type": brut.get("type"),
        "purchase_price_cents": montant,
        "purchase_price_raw": achat,
        "child_stock_id": brut.get("childStockId"),
        "motive": brut.get("motive"),
    }


async def lire_mouvements(db: FirebaseRTDB, business_id: str,
                          product_ids: Iterable[str], gte_ms: int,
                          lte_ms: int) -> list[dict]:
    """Les mouvements de ces produits dans la fenêtre — une lecture bornée par produit.

    `product_ids` est EXPLICITE et sans défaut : il n'existe pas de lecture globale
    des mouvements qui tienne (des milliers, sur un nœud sans index de temps au
    niveau du salon). Un appelant qui veut tout le catalogue le dit en passant tout
    le catalogue, et il sait alors ce qu'il paie."""
    sortie: list[dict] = []
    for pid in product_ids:
        brut = await db.get(f"{NOEUD_MOUVEMENTS}/{business_id}/{pid}",
                            range_on(INDEX_MOUVEMENT, gte_ms, lte_ms))
        if not isinstance(brut, dict):
            continue
        sortie += [mouvement(pid, mid, m) for mid, m in brut.items()
                   if isinstance(m, dict)]
    sortie.sort(key=lambda m: m.get("created_at") or 0)
    return sortie


async def lire_sorties_de_masse(db: FirebaseRTDB, business_id: str,
                                limite: int = 50) -> list[dict]:
    """Les sorties de stock groupées (inventaire, casse, péremption)."""
    brut = await db.get(f"{NOEUD_SORTIES_DE_MASSE}/{business_id}", limit_last(limite))
    if not isinstance(brut, dict):
        return []
    sorties = []
    for sid, s in brut.items():
        if not isinstance(s, dict):
            continue
        produits = s.get("products") or {}
        sorties.append({
            "id": sid,
            "created_at": s.get("createdAt"),
            "products_count": len(produits) if isinstance(produits, (dict, list)) else 0,
            "products": produits,
        })
    sorties.sort(key=lambda s: s.get("created_at") or 0)
    return sorties

