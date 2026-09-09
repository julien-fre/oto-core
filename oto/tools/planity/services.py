"""Le catalogue de prestations, et son prix.

Une prestation n'a pas de champ `price`. Elle a `prices`, un objet à trois formes
exclusives :

- `{"default": <centimes>}` — un prix ferme ;
- `{"min": <centimes>, "max": <centimes>}` — une fourchette (la couleur, la
  longueur de cheveux…) ;
- `{"onQuotation": true}` — sur devis.

Et elle peut n'en avoir aucune : `prices` est absent d'une prestation sur deux.

C'est le bug qui a rendu `price_eur: 0.00` sur TOUT le catalogue : le lecteur
cherchait `price`, ne le trouvait jamais, et rendait zéro. Un zéro ne lève rien —
il se lit comme une prestation offerte, et il l'a été pendant des semaines. D'où
la forme rendue ici : un `kind` qui DIT laquelle des quatre situations on a, plutôt
qu'un nombre qui ne peut pas dire qu'il n'existe pas.
"""
from __future__ import annotations

from typing import Optional

#: Ce que rend `prix` dans `kind`.
FIXE = "fixed"
FOURCHETTE = "range"
SUR_DEVIS = "on_quotation"
ABSENT = "unpriced"


def prix(prestation: dict) -> dict:
    """Le prix d'une prestation, en CENTIMES, avec la forme qu'il a réellement."""
    brut = (prestation or {}).get("prices")
    if not isinstance(brut, dict) or not brut:
        return {"kind": ABSENT, "default_cents": None,
                "min_cents": None, "max_cents": None}
    if brut.get("onQuotation"):
        return {"kind": SUR_DEVIS, "default_cents": None,
                "min_cents": None, "max_cents": None}
    defaut = _centimes(brut.get("default"))
    if defaut is not None:
        return {"kind": FIXE, "default_cents": defaut,
                "min_cents": defaut, "max_cents": defaut}
    mini, maxi = _centimes(brut.get("min")), _centimes(brut.get("max"))
    if mini is not None or maxi is not None:
        return {"kind": FOURCHETTE, "default_cents": None,
                "min_cents": mini, "max_cents": maxi}
    return {"kind": ABSENT, "default_cents": None, "min_cents": None, "max_cents": None}


def _centimes(v) -> Optional[int]:
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    return int(v)


def aplatir(catalogue: dict) -> list[dict]:
    """Le catalogue `{groupe: {children: {prestation}}}` à plat, prix compris.

    La suppression se porte AUX DEUX niveaux : une prestation vivante dans un
    groupe supprimé ne se propose plus. Les deux dates sont rendues séparément, et
    `deleted` dit ce qui compte — sans elle, un catalogue périmé se présente comme
    une offre."""
    sortie = []
    for gid, groupe in (catalogue or {}).items():
        if not isinstance(groupe, dict):
            continue
        enfants = groupe.get("children") or {}
        if not isinstance(enfants, dict):
            continue
        groupe_supprime = groupe.get("deletedAt")
        for sid, s in enfants.items():
            if not isinstance(s, dict):
                continue
            supprime = s.get("deletedAt")
            sortie.append({
                "id": sid,
                "category_id": gid,
                "category_name": (groupe.get("name") or "").strip(),
                "name": (s.get("name") or "").strip(),
                "duration_minutes": s.get("duration"),
                "bookable": s.get("bookable", True),
                "description": (s.get("description") or "")[:300],
                "sequence": s.get("sequence"),
                "deleted_at": supprime,
                "category_deleted_at": groupe_supprime,
                "deleted": supprime is not None or groupe_supprime is not None,
                "prices": prix(s),
            })
    return sortie
